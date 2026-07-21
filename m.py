import os
import sys
import re
from pathlib import Path

try:
    import pikepdf
    USE_PIKEPDF = True
except ImportError:
    USE_PIKEPDF = False

try:
    from pypdf import PdfWriter, PdfReader
except ImportError:
    from PyPDF2 import PdfWriter, PdfReader

def natural_sort_key(s):
    match = re.search(r'(\d+)\s*$', str(s))
    if match:
        num = int(match.group(1))
    else:
        num = 0
    return [num, str(s).lower()]

def merge_pdfs_pikepdf(input_folder, output_file):
    pdf_files = sorted(Path(input_folder).glob("*.pdf"), key=natural_sort_key)
    
    if not pdf_files:
        print(f"No PDF files found in {input_folder}")
        return False
    
    pdf = pikepdf.open(pdf_files[0])
    total_pages = len(pdf.pages)
    print(f"Added: {pdf_files[0].name} ({len(pdf.pages)} pages)")
    
    for pdf_file in pdf_files[1:]:
        try:
            src = pikepdf.open(pdf_file)
            pdf.pages.extend(src.pages)
            total_pages = len(pdf.pages)
            print(f"Added: {pdf_file.name} ({len(src.pages)} pages, total: {total_pages})")
            src.close()
        except Exception as e:
            print(f"Error reading {pdf_file.name}: {e}")
    
    try:
        pdf.save(output_file)
        pdf.close()
        total_size = sum(f.stat().st_size for f in pdf_files)
        output_size = os.path.getsize(output_file)
        print(f"\nMerged {len(pdf_files)} PDFs ({total_pages} pages) into {output_file}")
        print(f"Original total size: {total_size / 1024 / 1024:.2f} MB")
        print(f"Output size: {output_size / 1024 / 1024:.2f} MB ({output_size / total_size * 100:.1f}%)")
        return True
    except Exception as e:
        print(f"Error writing output: {e}")
        return False

def merge_pdfs_pypdf(input_folder, output_file):
    pdf_files = sorted(Path(input_folder).glob("*.pdf"), key=natural_sort_key)
    
    if not pdf_files:
        print(f"No PDF files found in {input_folder}")
        return False
    
    merger = PdfWriter()
    total_pages = 0
    
    for pdf_file in pdf_files:
        try:
            reader = PdfReader(pdf_file)
            for page in reader.pages:
                merger.add_page(page)
            total_pages += len(reader.pages)
            print(f"Added: {pdf_file.name} ({len(reader.pages)} pages, total: {total_pages})")
        except Exception as e:
            print(f"Error reading {pdf_file.name}: {e}")
    
    try:
        with open(output_file, "wb") as f:
            merger.write(f)
        total_size = sum(f.stat().st_size for f in pdf_files)
        output_size = os.path.getsize(output_file)
        print(f"\nMerged {len(pdf_files)} PDFs ({total_pages} pages) into {output_file}")
        print(f"Original total size: {total_size / 1024 / 1024:.2f} MB")
        print(f"Output size: {output_size / 1024 / 1024:.2f} MB ({output_size / total_size * 100:.1f}%)")
        return True
    except Exception as e:
        print(f"Error writing output: {e}")
        return False

def merge_pdfs(input_folder, output_file):
    print(f"Input folder: {input_folder}")
    print(f"Output file: {output_file}")
    print(f"Using: {'pikepdf' if USE_PIKEPDF else 'pypdf/PyPDF2'}")
    print("-" * 50)
    
    if USE_PIKEPDF:
        return merge_pdfs_pikepdf(input_folder, output_file)
    else:
        return merge_pdfs_pypdf(input_folder, output_file)

def process_folders(input_path, output_dir=None):
    input_path = Path(input_path)
    
    if output_dir is None:
        output_dir = input_path / "merged"
    else:
        output_dir = Path(output_dir)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if input_path.is_file() and input_path.suffix.lower() == '.pdf':
        print(f"Processing single file: {input_path.name}")
        output_file = output_dir / f"{input_path.stem}_merged.pdf"
        return merge_pdfs_pikepdf_single(input_path, output_file)
    
    if not input_path.is_dir():
        print(f"Error: {input_path} is not a valid folder or file")
        return
    
    subfolders = [f for f in input_path.iterdir() if f.is_dir()]
    
    if not subfolders:
        print(f"No subfolders found in {input_path}, merging PDFs directly...")
        output_file = output_dir / f"{input_path.name}.pdf"
        merge_pdfs(input_path, output_file)
        return
    
    print(f"Found {len(subfolders)} folders to process:")
    for folder in sorted(subfolders, key=natural_sort_key):
        pdf_count = len(list(folder.glob("*.pdf")))
        print(f"  - {folder.name} ({pdf_count} PDFs)")
    print("-" * 50)
    
    for folder in sorted(subfolders, key=natural_sort_key):
        print(f"\nProcessing: {folder.name}")
        output_file = output_dir / f"{folder.name}.pdf"
        merge_pdfs(folder, output_file)

def merge_pdfs_pikepdf_single(input_file, output_file):
    try:
        pdf = pikepdf.open(input_file)
        pdf.save(output_file)
        pdf.close()
        input_size = os.path.getsize(input_file)
        output_size = os.path.getsize(output_file)
        print(f"Copied: {input_file.name}")
        print(f"Input size: {input_size / 1024 / 1024:.2f} MB")
        print(f"Output size: {output_size / 1024 / 1024:.2f} MB ({output_size / input_size * 100:.1f}%)")
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python m.py <input_path> [output_dir]")
        print("")
        print("Examples:")
        print("  python m.py ./Komik                       # Process all folders in Komik/")
        print("  python m.py ./Komik/slime                  # Process single folder")
        print("  python m.py ./Komik ./output               # Output to custom directory")
        print("")
        print("Each subfolder will be merged into a single PDF with the folder name.")
        sys.exit(1)
    
    input_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None
    
    process_folders(input_path, output_dir)
