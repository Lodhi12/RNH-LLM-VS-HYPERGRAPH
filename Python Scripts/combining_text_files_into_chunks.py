from pathlib import Path

# Folder containing your .txt files
input_folder = Path(r"D:\PythonOCR\output_myths_and_facts_bangladesh_liberation_war_searchable\text")

# Extract the book number from the folder name
# "output_east_pakistan_1971_searchable" -> "east_pakistan_1971_searchable"
book_name = input_folder.parent.name

# Folder where the chunks will be created
output_folder = input_folder.parent / f"chunk_{book_name}"
output_folder.mkdir(exist_ok=True)

# Get all TXT files
# Skip full_document.txt and any existing chunk files
txt_files = sorted(
    [
        f for f in input_folder.glob("*.txt")
        if f.name.lower() != "full_document.txt"
        and not f.name.lower().startswith("chunk_")
    ],
    key=lambda f: f.name.lower()
)

# Combine every 10 files
for chunk_number, start in enumerate(range(0, len(txt_files), 10), start=1):
    files = txt_files[start:start + 10]

    # Example: chunk_1.txt, chunk_2.txt, etc.
    output_file = output_folder / f"chunk_{chunk_number}.txt"

    with output_file.open("w", encoding="utf-8") as out:
        for file in files:
            with file.open("r", encoding="utf-8") as inp:
                out.write(inp.read())

            # Separator between files
            out.write("\n\n")

    print(f"Created {output_file} from {len(files)} files")

print(
    f"\nDone! Combined {len(txt_files)} files into "
    f"{(len(txt_files) + 9) // 10} chunks."
)
