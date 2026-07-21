import os
import re
from PIL import Image
import shutil

def is_image_file(filename):
    """
    Check if a file is a supported image format by trying to open it with PIL
    """
    try:
        # Try to open the file as an image
        with Image.open(filename) as img:
            # If successful, it's a valid image file
            return True
    except (IOError, OSError):
        # If it fails, it's not a supported image file
        return False

def convert_to_rgb_if_needed(image):
    """
    Convert image to RGB if it's in a mode that's not compatible with PDF
    """
    if image.mode in ('RGBA', 'P', 'LA'):
        # Create a white background
        background = Image.new('RGB', image.size, (255, 255, 255))
        if image.mode == 'P':
            image = image.convert('RGBA')
        # Paste the image onto the white background
        if image.mode in ('RGBA', 'LA'):
            background.paste(image, mask=image.split()[-1])  # Use alpha channel as mask
        else:
            background.paste(image)
        return background
    elif image.mode != 'RGB':
        return image.convert('RGB')
    return image

def images_to_pdf(input_folder, output_file):
    if not os.path.exists(input_folder):
        print("Error: The input folder does not exist.")
        return

    # Get all files in the folder
    all_files = [f for f in os.listdir(input_folder) if os.path.isfile(os.path.join(input_folder, f))]
    
    # Filter only image files by trying to open them
    image_files = []
    for file in all_files:
        file_path = os.path.join(input_folder, file)
        if is_image_file(file_path):
            image_files.append(file)
    
    if not image_files:
        print("No valid image files found in the input folder.")
        return

    print(f"Found {len(image_files)} image files. Processing...")

    # Sort images numerically based on the numeric part of the filename
    def numeric_sort_key(filename):
        # Extract numeric part from filename using regex
        numbers = re.findall(r'\d+', filename)
        # Convert first number found to integer, or use infinity if no number found
        return int(numbers[0]) if numbers else float('inf')

    image_files = sorted(image_files, key=numeric_sort_key)

    # Load and process images in sorted order
    processed_images = []
    skipped_files = []
    
    for img_file in image_files:
        try:
            img_path = os.path.join(input_folder, img_file)
            image = Image.open(img_path)
            
            # Convert to RGB if needed for PDF compatibility
            image = convert_to_rgb_if_needed(image)
            processed_images.append(image)
            
        except Exception as e:
            skipped_files.append((img_file, str(e)))
            continue

    if not processed_images:
        print("No images could be processed successfully.")
        if skipped_files:
            print(f"Skipped {len(skipped_files)} files due to errors.")
        return

    # Create output directory if it doesn't exist
    output_dir = os.path.dirname(output_file)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"📁 Created output directory: {output_dir}")

    try:
        # Save all images into a single PDF with high quality
        processed_images[0].save(
            output_file,
            "PDF",
            resolution=300.0,
            save_all=True,
            append_images=processed_images[1:] if len(processed_images) > 1 else [],
            quality=95
        )
        print(f"✅ PDF created successfully!")
        print(f"📍 Location: {output_file}")
        print(f"📄 Total pages: {len(processed_images)}")
        if skipped_files:
            print(f"⚠️  Note: {len(skipped_files)} files were skipped due to errors.")
        
    except Exception as e:
        print(f"❌ Error creating PDF: {e}")
        return

    # Close all images to free memory
    for img in processed_images:
        img.close()

    # Remove only the contents of enhanced_images folder without deleting the folder itself
    if os.path.exists(input_folder):
        for filename in os.listdir(input_folder):
            file_path = os.path.join(input_folder, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                print(f'Failed to delete {file_path}. Reason: {e}')
        print(f"🗑️ Folder contents cleaned up successfully.")

def main():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    input_folder = os.path.join(current_dir, "enhanced_images")
    result_folder = os.path.join(current_dir, "Result")
    
    print("=== Image to PDF Converter ===")
    
    if not os.path.exists(input_folder):
        print(f"❌ Input folder 'enhanced_images' does not exist!")
        return
    
    # Create Result folder if it doesn't exist
    if not os.path.exists(result_folder):
        os.makedirs(result_folder)
        print(f"📁 Created Result folder: {result_folder}")
    
    output_file_name = input("Enter the name for the PDF file (e.g., my_comic): ").strip()
    
    if not output_file_name:
        print("❌ Please provide a valid filename.")
        return

    # Ensure the file name has a .pdf extension
    if not output_file_name.lower().endswith('.pdf'):
        output_file_name += '.pdf'

    # Save to Result directory
    output_file = os.path.join(result_folder, output_file_name)
    
    print(f"📤 Output will be saved to: {output_file}")
    print()
    
    images_to_pdf(input_folder, output_file)

if __name__ == "__main__":
    main()