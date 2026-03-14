#!/usr/bin/env python3
"""
Smart PDF Extractor for PrivatTeacher
Removes boilerplate (page numbers, headers, footers, copyright)
Extracts main content intelligently
"""

import re
import sys
from pathlib import Path

try:
    import PyPDF2
except ImportError:
    print("Installing PyPDF2...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "PyPDF2"])
    import PyPDF2


class SmartPDFExtractor:
    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.content = []
        
    def extract_all_text(self) -> str:
        """Extract all text from PDF"""
        text = ""
        try:
            with open(self.pdf_path, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                total_pages = len(pdf_reader.pages)
                print(f"📄 Total pages: {total_pages}")
                
                for page_num, page in enumerate(pdf_reader.pages):
                    page_text = page.extract_text()
                    if page_text:
                        text += f"\n--- PAGE {page_num + 1} ---\n"
                        text += page_text
                        
        except Exception as e:
            print(f"❌ Error extracting PDF: {e}")
            return ""
        
        return text
    
    def remove_boilerplate(self, text: str) -> str:
        """Remove headers, footers, page numbers, copyright, etc."""
        
        lines = text.split('\n')
        filtered_lines = []
        
        for line in lines:
            # Skip page markers
            if re.match(r'^--- PAGE \d+ ---$', line):
                continue
            
            # Skip page numbers alone (e.g., "6", "71")
            if re.match(r'^\d{1,3}$', line.strip()):
                continue
            
            # Skip header/footer patterns (e.g., "åTME102", "Kapitel 1")
            if re.match(r'^(å|Art\.-Nr\.|Copyright|Telefon|Internet|http)', line):
                continue
            
            # Skip "Stichwortverzeichnis", "Literaturverzeichnis", "Inhaltsverzeichnis"
            if any(x in line for x in ["verzeichnis", "Verzeichnis", "index"]):
                if line.strip().isupper() or len(line.strip()) < 50:
                    continue
            
            # Skip empty lines (but keep some for readability)
            if line.strip() == "" and len(filtered_lines) > 0:
                if filtered_lines[-1].strip() != "":
                    filtered_lines.append("")
                continue
            
            # Skip very short lines that are likely headers/footers
            if len(line.strip()) < 5 and not any(c.isdigit() for c in line):
                continue
            
            filtered_lines.append(line)
        
        return '\n'.join(filtered_lines)
    
    def extract_chapters(self, text: str) -> dict:
        """Identify and extract chapters"""
        chapters = {}
        
        # Pattern for chapter headers
        chapter_pattern = r'^(\d+\.?\d*)\s+(.+?)(?=^\d+\.?\d*\s|$)'
        
        # For now, split by "## " or "# " headers
        lines = text.split('\n')
        current_chapter = None
        current_content = []
        
        for line in lines:
            # Detect chapter header (e.g., "1 Statik ebener Tragwerke")
            if re.match(r'^(\d+)\s+([A-Z].*?)$', line):
                if current_chapter:
                    chapters[current_chapter] = '\n'.join(current_content)
                match = re.match(r'^(\d+)\s+(.+?)$', line)
                current_chapter = match.group(0) if match else "Unknown"
                current_content = [line]
            elif current_chapter:
                current_content.append(line)
        
        if current_chapter:
            chapters[current_chapter] = '\n'.join(current_content)
        
        return chapters
    
    def save_cleaned_text(self, text: str, output_path: str):
        """Save cleaned text to file"""
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f"✅ Cleaned text saved to: {output_path}")
        
        # Print stats
        lines = text.split('\n')
        non_empty_lines = [l for l in lines if l.strip()]
        print(f"📊 Stats: {len(non_empty_lines)} content lines, {len(text)} characters")


def main():
    pdf_path = "/data/.openclaw/workspace/lernbot/scripts/TME102_11287_K1113_OC.pdf"
    
    print("🚀 Starting Smart PDF Extraction...")
    print(f"📂 File: {pdf_path}\n")
    
    extractor = SmartPDFExtractor(pdf_path)
    
    # Step 1: Extract all text
    print("Step 1: Extracting text from PDF...")
    raw_text = extractor.extract_all_text()
    print(f"✅ Extracted {len(raw_text)} characters\n")
    
    # Step 2: Remove boilerplate
    print("Step 2: Removing boilerplate (headers, footers, page numbers)...")
    cleaned_text = extractor.remove_boilerplate(raw_text)
    print(f"✅ Cleaned {len(cleaned_text)} characters (removed {len(raw_text) - len(cleaned_text)} chars)\n")
    
    # Step 3: Save
    output_path = "/data/.openclaw/workspace/lernbot/output/TME102_cleaned.txt"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    extractor.save_cleaned_text(cleaned_text, output_path)
    
    # Step 4: Preview first chapter
    print("\n" + "="*60)
    print("PREVIEW: First 1000 characters of cleaned text")
    print("="*60)
    preview = cleaned_text[:1000]
    print(preview)
    print("...")
    print("="*60)


if __name__ == "__main__":
    main()
