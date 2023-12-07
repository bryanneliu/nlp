import argparse
import logging
import sys

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, array, explode, collect_set, countDistinct, sum, max, collect_list, struct

from common import (
    s3_working_folder,
    format_date, s3_path_exists,
    get_tc_missing_tokens_udf
)

from marketplace_utils import (
    get_marketplace_name, get_region_name
)

logger = logging.getLogger(__name__)
logging.basicConfig(
    #format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    format="%(message)s",
    datefmt="%m/%d/%Y %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
    level=logging.INFO,
)

spark = (
    SparkSession.builder.master("yarn")
    .appName("get_tc_missing_tokens")
    .enableHiveSupport()
    .getOrCreate()
)

sc = spark.sparkContext

def process_args():
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument(
        "--marketplace_id",
        type=int,
        default=1,
        help="Specify solr_index marketplaceid",
        required=True
    )

    parser.add_argument(
        "--solr_index_latest_ds",
        type=str,
        default="2022-12-19",
        help="Specify solr_index ds",
        required=True
    )

    args, _ = parser.parse_known_args()

    return args


def tc_based_expansion(s3_not_matched_tcs, s3_tc_based_missing_tokens):
    not_matched_tcs = spark.read.parquet(s3_not_matched_tcs)
    expansion_udf = get_tc_missing_tokens_udf()
    tc_based_missing_tokens = (
        not_matched_tcs
            .withColumn(
                "expansions",
                expansion_udf(
                    col("not_matched_tc_data"),
                    col("index_tokens")
                )
            )
            .drop("not_matched_tc_data", "index_tokens")
            .where(col("expansions") != array())
    )

    logger.info(f"asin count with tc based missing tokens: {tc_based_missing_tokens.count()}")

    asin_missing_tokens = (
        tc_based_missing_tokens
            .select("asin", explode(col("expansions")))
            .select("asin", "col.expansion", "col.tc")
    )

    asin_missing_tokens = asin_missing_tokens.coalesce(2000)
    asin_missing_tokens.write.mode("overwrite").parquet(s3_tc_based_missing_tokens)


def main():
    # Initialization
    args = process_args()

    marketplace_name = get_marketplace_name(args.marketplace_id).lower()
    region = get_region_name(args.marketplace_id).upper()
    solr_index_latest_date = format_date(args.solr_index_latest_ds, "%Y-%m-%d")

    working_folder = f"{s3_working_folder}{region}/{marketplace_name}/solr_index_{solr_index_latest_date}/"
    s3_not_matched_tcs = f"{working_folder}not_matched_tcs/"
    s3_tc_based_missing_tokens = f"{working_folder}tc_based_missing_tokens/"

    if s3_path_exists(sc, s3_tc_based_missing_tokens):
        logger.info(f"{s3_tc_based_missing_tokens} exists, return")
        return

    tc_based_expansion(s3_not_matched_tcs, s3_tc_based_missing_tokens)


if __name__ == "__main__":
    main()
