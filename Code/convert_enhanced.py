import os
import re
from PIL import Image
import shutil

def images_to_pdf(input_folder, output_file):
    if not os.path.exists(input_folder):
        print("Error: The input folder does not exist.")
        return
    
    # Get image files with supported extensions
    image_files = [f for f in os.listdir(input_folder) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
    if not image_files:
        print("No image files found in the input folder.")
        return
    
    # Sort images numerically based on the numeric part of the filename
    def numeric_sort_key(filename):
        # Extract numeric part from filename using regex
        numbers = re.findall(r'\d+', filename)
        # Convert first number found to integer, or use infinity if no number found
        return int(numbers[0]) if numbers else float('inf')
    
    image_files = sorted(image_files, key=numeric_sort_key)
    
    # Load images in sorted order
    images = [Image.open(os.path.join(input_folder, img)) for img in image_files]
    
    # Create output directory if it doesn't exist
    output_dir = os.path.dirname(output_file)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Save all images into a single PDF with high quality
    images[0].save(
        output_file,
        "PDF",
        resolution=300,
        save_all=True,
        append_images=images[1:],
        quality=95
    )
    print(f"PDF created and saved as: {output_file}")

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
        print(f"🗑️ Removed contents of folder: {input_folder} (folder kept intact)")

def main():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    input_folder = os.path.join(current_dir, "enhanced_images")
    output_file_name = input("Enter the name for the PDF file (e.g., my_comic): ")
    
    # Ensure the file name has a .pdf extension
    if not output_file_name.lower().endswith('.pdf'):
        output_file_name += '.pdf'
    
    output_file = os.path.join(current_dir, "Result", output_file_name)
    images_to_pdf(input_folder, output_file)

if __name__ == "__main__":
    main()