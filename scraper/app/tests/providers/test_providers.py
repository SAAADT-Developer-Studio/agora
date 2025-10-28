from app.providers.enums import ProviderKey
import os
import boto3


def test_if_provider_logos_exist():
    dir_path = os.path.dirname(os.path.realpath(__file__))
    logos_path_relative = "../../../data/logos"
    logos_dir = os.path.join(dir_path, logos_path_relative)

    # Check both 60 and 160 sizes
    for size in ["60", "160"]:
        size_dir = os.path.join(logos_dir, size)
        logo_filenames = {os.path.splitext(filename)[0] for filename in os.listdir(size_dir)}
        for key in ProviderKey:
            if key.value not in logo_filenames:
                raise AssertionError(f"Logo for {key.value} does not exist in {size_dir}")


# TODO: check if logos are synced with the R2 bucket
