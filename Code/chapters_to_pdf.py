import os
import re
from PIL import Image
import shutil
import glob
from pathlib import Path

class ComicToPDFConverter:
    def __init__(self):
        self.supported_formats = ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif']
        self.comics_directory = r"D:\zayn\comic_downloader\Comics"
        
    def is_image_file(self, filename):
        """
        Check if a file is a supported image format by trying to open it with PIL
        """
        try:
            with Image.open(filename) as img:
                return True
        except (IOError, OSError):
            return False

    def convert_to_rgb_if_needed(self, image):
        """
        Convert image to RGB if it's in a mode that's not compatible with PDF
        """
        if image.mode in ('RGBA', 'P', 'LA'):
            background = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            if image.mode in ('RGBA', 'LA'):
                background.paste(image, mask=image.split()[-1])
            else:
                background.paste(image)
            return background
        elif image.mode != 'RGB':
            return image.convert('RGB')
        return image

    def get_available_comics(self):
        """Get list of all available comics"""
        try:
            if not os.path.exists(self.comics_directory):
                print(f"❌ Comics directory not found: {self.comics_directory}")
                return []
            
            comics = []
            for item in os.listdir(self.comics_directory):
                comic_path = os.path.join(self.comics_directory, item)
                if os.path.isdir(comic_path):
                    chapters = self.get_chapters_in_comic(comic_path)
                    if chapters:
                        comics.append({
                            'name': item,
                            'path': comic_path,
                            'chapters': len(chapters),
                            'chapter_list': chapters
                        })
            
            return comics
        except Exception as e:
            print(f"❌ Error scanning comics directory: {e}")
            return []
    
    def get_chapters_in_comic(self, comic_path):
        """Get list of chapters in a comic"""
        try:
            chapters = []
            for item in os.listdir(comic_path):
                item_path = os.path.join(comic_path, item)
                if os.path.isdir(item_path) and item.startswith("Chapter_"):
                    try:
                        chapter_num = int(item.replace("Chapter_", ""))
                        chapters.append((chapter_num, item_path))
                    except ValueError:
                        continue
            
            chapters.sort(key=lambda x: x[0])
            return chapters
        except Exception as e:
            return []
    
    def display_comic_menu(self, comics):
        """Display comic selection menu"""
        print("\n📚 Available Comics:")
        print("=" * 60)
        
        for i, comic in enumerate(comics, 1):
            print(f"{i:2d}. {comic['name']} ({comic['chapters']} chapters)")
        
        print("=" * 60)
        return comics
    
    def get_user_comic_selection(self, comics):
        """Get comic selection from user"""
        while True:
            try:
                choice = input(f"\nSelect comic (1-{len(comics)}) or 'q' to quit: ").strip().lower()
                
                if choice == 'q':
                    return None
                
                choice_num = int(choice)
                if 1 <= choice_num <= len(comics):
                    return comics[choice_num - 1]
                else:
                    print(f"❌ Please enter a number between 1 and {len(comics)}")
            except ValueError:
                print("❌ Please enter a valid number or 'q' to quit")

    def get_conversion_mode(self):
        """Get conversion mode from user"""
        print("\n📄 Conversion Mode:")
        print("1. Convert chapter range")
        print("2. Convert single chapter")
        print("3. Convert all chapters")
        
        while True:
            try:
                choice = input("Select mode (1-3): ").strip()
                if choice in ['1', '2', '3']:
                    return int(choice)
                else:
                    print("❌ Please enter 1, 2, or 3")
            except ValueError:
                print("❌ Please enter a valid number")

    def get_chapter_range(self, selected_comic):
        """Get chapter range to convert"""
        chapters = selected_comic['chapter_list']
        min_chapter = min(chapters, key=lambda x: x[0])[0]
        max_chapter = max(chapters, key=lambda x: x[0])[0]
        
        print(f"\n📖 Comic: {selected_comic['name']}")
        print(f"📋 Available chapters: {min_chapter} - {max_chapter}")
        print(f"📊 Total chapters: {len(chapters)}")
        
        while True:
            try:
                start_input = input(f"Start chapter (or Enter for {min_chapter}): ").strip()
                start_chapter = int(start_input) if start_input else min_chapter
                
                end_input = input(f"End chapter (or Enter for {max_chapter}): ").strip()
                end_chapter = int(end_input) if end_input else max_chapter
                
                if start_chapter > end_chapter:
                    print("❌ Start chapter cannot be greater than end chapter!")
                    continue
                
                if start_chapter < min_chapter or end_chapter > max_chapter:
                    print(f"❌ Chapter range must be between {min_chapter} and {max_chapter}")
                    continue
                
                return start_chapter, end_chapter
                
            except ValueError:
                print("❌ Please enter valid chapter numbers")

    def get_single_chapter(self, selected_comic):
        """Get single chapter to convert"""
        chapters = selected_comic['chapter_list']
        available_chapters = [ch[0] for ch in chapters]
        min_chapter = min(available_chapters)
        max_chapter = max(available_chapters)
        
        print(f"\n📖 Comic: {selected_comic['name']}")
        print(f"📋 Available chapters: {min_chapter} - {max_chapter} (Total: {len(available_chapters)})")
        
        while True:
            try:
                chapter_input = input("Enter chapter number: ").strip()
                chapter_num = int(chapter_input)
                
                if chapter_num in available_chapters:
                    return chapter_num, chapter_num
                else:
                    print(f"❌ Chapter {chapter_num} not found. Range: {min_chapter}-{max_chapter}")
                
            except ValueError:
                print("❌ Please enter a valid chapter number")

    def get_image_files(self, chapter_path):
        """Get all image files in chapter with proper sorting"""
        image_files = []
        
        # Get all files in the folder
        all_files = [f for f in os.listdir(chapter_path) if os.path.isfile(os.path.join(chapter_path, f))]
        
        # Filter only image files by trying to open them
        for file in all_files:
            file_path = os.path.join(chapter_path, file)
            if self.is_image_file(file_path):
                image_files.append(file_path)
        
        if not image_files:
            return []

        # Sort images numerically based on the numeric part of the filename
        def numeric_sort_key(filename):
            basename = os.path.basename(filename)
            numbers = re.findall(r'\d+', basename)
            return int(numbers[0]) if numbers else float('inf')

        image_files.sort(key=numeric_sort_key)
        return image_files

    def images_to_pdf(self, image_files, output_file):
        """Convert images to PDF using the working method from the first code"""
        if not image_files:
            print("No valid image files found.")
            return False

        print(f"Found {len(image_files)} image files. Processing...")

        # Load and process images
        processed_images = []
        skipped_files = []
        
        for img_file in image_files:
            try:
                image = Image.open(img_file)
                image = self.convert_to_rgb_if_needed(image)
                processed_images.append(image)
                
            except Exception as e:
                skipped_files.append((os.path.basename(img_file), str(e)))
                continue

        if not processed_images:
            print("No images could be processed successfully.")
            if skipped_files:
                print(f"Skipped {len(skipped_files)} files due to errors.")
            return False

        # Create output directory if it doesn't exist
        output_dir = os.path.dirname(output_file)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

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
            
            # Close all images to free memory
            for img in processed_images:
                img.close()
            
            return True
            
        except Exception as e:
            print(f"❌ Error creating PDF: {e}")
            return False

    def convert_chapter_to_pdf(self, chapter_path, output_path):
        """Convert single chapter to PDF"""
        try:
            chapter_name = os.path.basename(chapter_path)
            print(f"📄 Converting {chapter_name}...")
            
            # Get image files
            image_files = self.get_image_files(chapter_path)
            
            if not image_files:
                print(f"⚠️  No images found in {chapter_name}")
                return False
            
            # Convert to PDF
            if self.images_to_pdf(image_files, output_path):
                file_size = os.path.getsize(output_path) / 1024 / 1024  # MB
                print(f"✅ {chapter_name} converted successfully!")
                print(f"📍 Location: {output_path}")
                print(f"📄 Total pages: {len(image_files)}")
                print(f"💾 File size: {file_size:.1f}MB")
                return True
            else:
                return False
                
        except Exception as e:
            print(f"❌ Error converting {os.path.basename(chapter_path)}: {e}")
            return False

    def convert_selected_chapters(self, selected_comic, start_chapter, end_chapter):
        """Convert selected chapters to PDF"""
        try:
            comic_path = selected_comic['path']
            comic_name = selected_comic['name']
            
            # Create Result directory in comic folder
            result_dir = os.path.join(comic_path, "Result")
            os.makedirs(result_dir, exist_ok=True)
            
            # Filter chapters by range
            chapters_to_convert = []
            for chapter_num, chapter_path in selected_comic['chapter_list']:
                if start_chapter <= chapter_num <= end_chapter:
                    chapters_to_convert.append((chapter_num, chapter_path))
            
            if not chapters_to_convert:
                print(f"❌ No chapters found in range {start_chapter} to {end_chapter}")
                return
            
            print(f"\n🔄 Converting {len(chapters_to_convert)} chapters to PDF...")
            print(f"📁 Output directory: {result_dir}")
            print("=" * 70)
            
            successful_conversions = 0
            failed_conversions = []
            
            for i, (chapter_num, chapter_path) in enumerate(chapters_to_convert):
                chapter_name = os.path.basename(chapter_path)
                
                print(f"\n📖 Progress: {i+1}/{len(chapters_to_convert)} - {chapter_name}")
                
                pdf_filename = f"{chapter_name}.pdf"
                pdf_path = os.path.join(result_dir, pdf_filename)
                
                # Skip if PDF already exists
                if os.path.exists(pdf_path):
                    overwrite = input(f"   PDF already exists. Overwrite? (y/n): ").lower().strip()
                    if overwrite != 'y':
                        print(f"   ⏭️  Skipped {chapter_name}")
                        continue
                
                # Convert chapter
                if self.convert_chapter_to_pdf(chapter_path, pdf_path):
                    successful_conversions += 1
                else:
                    failed_conversions.append(chapter_name)
            
            # Final summary
            print("\n" + "=" * 70)
            print(f"🎉 Conversion Complete for {comic_name}!")
            print(f"✅ Successful: {successful_conversions}/{len(chapters_to_convert)} chapters")
            
            if failed_conversions:
                print(f"❌ Failed chapters: {len(failed_conversions)}")
                for failed in failed_conversions:
                    print(f"   • {failed}")
            
            # Calculate total folder size
            total_size = sum(os.path.getsize(os.path.join(root, f)) 
                           for root, _, files in os.walk(result_dir) 
                           for f in files if f.endswith('.pdf')) / (1024 * 1024)
            
            print(f"💾 Total PDF size: {total_size:.1f}MB")
            print(f"📁 PDFs saved in: {result_dir}")
            
        except Exception as e:
            print(f"❌ Error in conversion process: {e}")

def main():
    """Main function to run the converter"""
    converter = ComicToPDFConverter()
    
    print("🔄 Comic Chapter to PDF Converter v3.0")
    print("=" * 60)
    print("🎨 Features: High Quality PDF, Chapter Range Selection")
    print(f"📂 Scanning: {converter.comics_directory}")
    
    # Scan for available comics
    print("\n🔍 Scanning for comics...", end='', flush=True)
    comics = converter.get_available_comics()
    print(" ✅")
    
    if not comics:
        print("❌ No comics found in the directory!")
        print(f"📁 Make sure comics are in: {converter.comics_directory}")
        return
    
    # Display menu and get selection
    comics = converter.display_comic_menu(comics)
    selected_comic = converter.get_user_comic_selection(comics)
    
    if not selected_comic:
        print("👋 Goodbye!")
        return
    
    # Get conversion mode
    mode = converter.get_conversion_mode()
    
    if mode == 1:  # Range
        start_chapter, end_chapter = converter.get_chapter_range(selected_comic)
    elif mode == 2:  # Single chapter
        start_chapter, end_chapter = converter.get_single_chapter(selected_comic)
    else:  # All chapters
        chapters = selected_comic['chapter_list']
        start_chapter = min(chapters, key=lambda x: x[0])[0]
        end_chapter = max(chapters, key=lambda x: x[0])[0]
    
    # Start conversion
    confirm = input("\n🚀 Start conversion? (y/n): ").lower().strip()
    if confirm != 'y':
        print("❌ Conversion cancelled")
        return
    
    # Start conversion
    converter.convert_selected_chapters(selected_comic, start_chapter, end_chapter)

if __name__ == "__main__":
    main()