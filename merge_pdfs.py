import os
import re
from PyPDF2 import PdfReader, PdfWriter

def sanitize_filename(filename):
    """Clean filename while keeping special characters."""
    # Remove invalid characters but preserve []() and Unicode
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', filename).strip()

def merge_pdfs(input_folder, output_file):
    """Merge PDFs without quality loss."""
    merger = PdfWriter()
    
    # Natural sorting (1, 2,...10 instead of 1, 10, 2)
    pdf_files = sorted(
        [f for f in os.listdir(input_folder) if f.lower().endswith('.pdf')],
        key=lambda x: [int(c) if c.isdigit() else c for c in re.split('([0-9]+)', x)]
    )
    
    if not pdf_files:
        print("Error: No PDF files found in the folder.")
        return
    
    print(f"\nFound {len(pdf_files)} PDFs to merge. Processing...")
    
    for pdf_file in pdf_files:
        try:
            pdf_path = os.path.join(input_folder, pdf_file)
            with open(pdf_path, 'rb') as f:
                pdf_reader = PdfReader(f)
                for page in pdf_reader.pages:
                    merger.add_page(page)
        except Exception as e:
            print(f"✗ Error processing {pdf_file}: {str(e)}")
    
    # Create output directory if it doesn't exist
    output_dir = os.path.dirname(output_file)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"📁 Created output directory: {output_dir}")
    
    try:
        with open(output_file, 'wb') as f:
            merger.write(f)
        print(f"✅ PDF merged successfully!")
        print(f"📍 Location: {output_file}")
        print(f"📄 Total files merged: {len(pdf_files)}")
    except Exception as e:
        print(f"❌ Save failed: {str(e)}")
    finally:
        merger.close()

def get_output_filename():
    """Get valid output filename from user."""
    while True:
        filename = input("\nEnter output PDF name (e.g., [Author] Title): ").strip()
        if not filename:
            print("Please enter a name")
            continue
        
        filename = sanitize_filename(filename)
        if not filename.endswith('.pdf'):
            filename += '.pdf'
        
        if len(filename) > 255:
            print("Filename too long (max 255 chars)")
            continue
        
        return filename

def main():
    print("📄 PDF Merger Tool (Supports Special Characters)")
    print("-------------------------------------------")
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    input_folder = os.path.join(current_dir, "merged_sources")
    result_folder = os.path.join(current_dir, "Result")
    
    if not os.path.exists(input_folder):
        print(f"❌ Error: 'merged_sources' folder not found!")
        return
    
    # Create Result folder if it doesn't exist
    if not os.path.exists(result_folder):
        os.makedirs(result_folder)
        print(f"📁 Created Result folder: {result_folder}")
    
    output_file = get_output_filename()
    output_path = os.path.join(result_folder, output_file)
    
    if os.path.exists(output_path):
        overwrite = input(f"'{output_file}' already exists in Result folder. Overwrite? (y/n): ").lower()
        if overwrite != 'y':
            print("Merge cancelled")
            return
    
    print(f"📤 Output will be saved to: {output_path}")
    
    merge_pdfs(input_folder, output_path)

if __name__ == "__main__":
    main()