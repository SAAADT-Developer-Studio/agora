from PIL import Image
import os


def process_image_for_web(
    image_path,
    output_folder,
    base_filename,
    size=(60, 60),
    webp_quality=85,
    create_webp=True,
    create_jpeg_fallback=True,
    jpeg_quality=85,
):
    try:
        with Image.open(image_path) as img:
            img = img.resize(size, Image.LANCZOS)  # High-quality downsampling

            # Ensure output folder exists
            os.makedirs(output_folder, exist_ok=True)

            if create_webp:
                webp_output_path = os.path.join(output_folder, f"{base_filename}.webp")
                img.save(webp_output_path, "webp", optimize=True, quality=webp_quality)
                print(f"Saved WebP: {webp_output_path}")

            if create_jpeg_fallback:
                jpeg_output_path = os.path.join(output_folder, f"{base_filename}.jpg")
                img.save(jpeg_output_path, "jpeg", optimize=True, quality=jpeg_quality)
                print(f"Saved JPEG fallback: {jpeg_output_path}")

    except Exception as e:
        print(f"Error processing {image_path}: {e}")


dir_path = os.path.dirname(os.path.realpath(__file__))
input_image_dir = os.path.join(dir_path, "../data/logos_source")
output_image_dir = os.path.join(dir_path, "../data/logos")

if not os.path.exists(output_image_dir):
    os.makedirs(output_image_dir)

for filename in os.listdir(input_image_dir):
    if filename.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp")):
        input_path = os.path.join(input_image_dir, filename)
        base_name = os.path.splitext(filename)[0]

        process_image_for_web(
            image_path=input_path,
            output_folder=output_image_dir,
            base_filename=base_name,
            create_webp=True,
            create_jpeg_fallback=False,
        )
