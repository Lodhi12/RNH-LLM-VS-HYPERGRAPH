
import json
import glob
import os
import re
from openai import OpenAI


# =========================================================
# CONFIGURATION
# =========================================================

client = OpenAI(
    base_url="http://localhost:1234/v1",
    api_key="bionic"
)

MODEL_NAME = "qwen3-14b"


# =========================================================
# PATHS
# =========================================================

# Folder containing full_document.txt
TEXT_FOLDER = r"D:\PythonOCR\output_myths_and_facts_bangladesh_liberation_war_searchable\text"

# Folder containing:
# chunk_2_1.txt
# chunk_2_2.txt
# chunk_2_3.txt
# etc.
CHUNK_FOLDER = r"D:\PythonOCR\output_myths_and_facts_bangladesh_liberation_war_searchable\chunk_output_myths_and_facts_bangladesh_liberation_war_searchable"

# Final output
OUTPUT_FILE = r"D:\PythonOCR\output_myths_and_facts_bangladesh_liberation_war_searchable\extracted_claims_output_myths_and_facts_bangladesh_liberation_war_searchable.json"

# Source document
FULL_DOCUMENT = os.path.join(
    TEXT_FOLDER,
    "full_document.txt"
)


# =========================================================
# JSON SCHEMA: BOOK METADATA
# =========================================================

METADATA_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string"
        },
        "author": {
            "type": "string"
        },
        "publication_year": {
            "type": "string"
        },
        "publisher": {
            "type": "string"
        },
        "edition": {
            "type": "string"
        },
        "language": {
            "type": "string"
        }
    },
    "required": [
        "title",
        "author",
        "publication_year",
        "publisher",
        "edition",
        "language"
    ],
    "additionalProperties": False
}


# =========================================================
# JSON SCHEMA: CLAIMS
# =========================================================

CLAIMS_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {
                        "type": "string"
                    },
                    "actor": {
                        "type": "string"
                    },
                    "event": {
                        "type": "string"
                    },
                    "location": {
                        "type": "string"
                    },
                    "time": {
                        "type": "string"
                    },
                    "frame": {
                        "type": "string"
                    },
                    "source": {
                        "type": "string"
                    }
                },
                "required": [
                    "claim",
                    "actor",
                    "event",
                    "location",
                    "time",
                    "frame",
                    "source"
                ],
                "additionalProperties": False
            }
        }
    },
    "required": [
        "claims"
    ],
    "additionalProperties": False
}


# =========================================================
# EXTRACT BOOK METADATA
# =========================================================

def extract_book_metadata():

    print()
    print("=" * 70)
    print("EXTRACTING BOOK METADATA")
    print("=" * 70)

    # -----------------------------------------------------
    # Read full_document.txt
    # -----------------------------------------------------

    try:

        with open(
            FULL_DOCUMENT,
            "r",
            encoding="utf-8"
        ) as f:

            full_text = f.read()

    except Exception as e:

        print(
            f"ERROR reading full_document.txt: {e}"
        )

        return {
            "title": "N/A",
            "author": "N/A",
            "publication_year": "N/A",
            "publisher": "N/A",
            "edition": "N/A",
            "language": "N/A"
        }

    # -----------------------------------------------------
    # First 2,000 words
    # -----------------------------------------------------

    words = full_text.split()

    first_2000_words = " ".join(
        words[:2000]
    )

    print(
        f"Read first "
        f"{min(2000, len(words))} words "
        f"for metadata extraction."
    )

    # -----------------------------------------------------
    # Metadata prompt
    # -----------------------------------------------------

    system_prompt = """
You are an expert bibliographic information extraction assistant.

Identify the metadata of the book from the provided beginning
of the book.

Extract ONLY information supported by the provided text.

Do NOT invent or guess bibliographic information.

Fields:

- title:
  Full title of the book.

- author:
  Author or authors of the book.

- publication_year:
  Publication year if available.

- publisher:
  Publisher if available.

- edition:
  Edition information if available.

- language:
  Identify the PRIMARY LANGUAGE of the book from the actual
  text provided.

IMPORTANT LANGUAGE RULE:

You should identify the language from the text itself.

Do NOT require the book to explicitly state:
"Language: English"

For example, if the provided text is clearly written in English,
return:

"language": "English"

If the provided text is clearly written in Urdu, return:

"language": "Urdu"

If the provided text is clearly written in Bengali, return:

"language": "Bengali"

If the text is primarily English but contains occasional words
or quotations in another language, identify English as the
primary language.

Use "N/A" only if the language genuinely cannot be determined.

For metadata that is not available, use "N/A".

Return only the structured JSON requested by the schema.
"""

    try:

        response = client.chat.completions.create(

            model=MODEL_NAME,

            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": (
                        "Identify the book metadata from "
                        "the following text:\n\n"
                        f"{first_2000_words}"
                    )
                }
            ],

            temperature=0,

            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "book_metadata",
                    "strict": True,
                    "schema": METADATA_SCHEMA
                }
            }
        )

        content = (
            response
            .choices[0]
            .message
            .content
            .strip()
        )

        metadata = json.loads(
            content
        )

        print()
        print("Book metadata extracted:")
        print(
            json.dumps(
                metadata,
                ensure_ascii=False,
                indent=2
            )
        )

        return metadata

    except Exception as e:

        print()
        print(
            f"ERROR extracting book metadata: {e}"
        )

        return {
            "title": "N/A",
            "author": "N/A",
            "publication_year": "N/A",
            "publisher": "N/A",
            "edition": "N/A",
            "language": "N/A"
        }


# =========================================================
# EXTRACT CLAIMS FROM ONE CHUNK
# =========================================================

def extract_claims_from_chunk(
    text_chunk,
    chunk_id
):

    system_prompt = """
You are an expert analytical assistant.

Extract ALL distinct factual or substantive claims from the
provided text.

A claim is a statement presented in the text as an assertion,
report, allegation, observation, description, historical claim,
statistical claim, or attributed statement.

Each claim must contain:

- claim:
  The complete core assertion.

- actor:
  The entity, person, group, organization, government, or subject
  responsible for the action or central to the claim.

- event:
  The action, event, condition, or outcome described by the claim.

- location:
  Physical or geopolitical location if available.
  Otherwise "N/A".

- time:
  Temporal reference if available.
  Otherwise "N/A".

- frame:
  The perspective or domain of the claim, such as:
  Political, Military, Economic, Social, Historical,
  Humanitarian, Legal, Technical, Diplomatic, etc.

- source:
  The person, organization, document, eyewitness, speaker,
  author, or other source to whom the claim is attributed.
  If the claim is directly presented by the text without
  identifiable attribution, use "N/A".

IMPORTANT RULES:

1. Extract ALL distinct claims.
2. Do not invent facts.
3. Do not add information that is not supported by the text.
4. Preserve the meaning of the original claim.
5. Keep separate claims separate.
6. Do not merge unrelated claims.
7. If a field cannot be determined, use "N/A".
8. Return only the structured JSON requested by the schema.

If the text contains claims attributed to someone, preserve
that attribution in the "source" field.
"""

    try:

        response = client.chat.completions.create(

            model=MODEL_NAME,

            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": (
                        f"Extract all claims from "
                        f"{chunk_id}.\n\n"
                        "TEXT:\n\n"
                        f"{text_chunk}"
                    )
                }
            ],

            temperature=0.1,

            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "claims_extraction",
                    "strict": True,
                    "schema": CLAIMS_SCHEMA
                }
            }
        )

        content = (
            response
            .choices[0]
            .message
            .content
            .strip()
        )

        data = json.loads(
            content
        )

        claims = data.get(
            "claims",
            []
        )

        if not isinstance(
            claims,
            list
        ):
            print(
                "ERROR: claims is not a list."
            )

            return None

        return claims

    except Exception as e:

        print()
        print(
            f"ERROR extracting claims "
            f"from {chunk_id}:"
        )

        print(e)

        return None


# =========================================================
# NUMERIC SORTING OF CHUNKS
# =========================================================

def chunk_sort_key(filepath):

    filename = os.path.basename(
        filepath
    )

    # Matches:
    #
    # chunk_2_1.txt
    # chunk_2_10.txt
    # chunk_2_22.txt

    match = re.search(
        r"chunk_(\d+)_(\d+)\.txt$",
        filename,
        re.IGNORECASE
    )

    if match:

        book_number = int(
            match.group(1)
        )

        chunk_number = int(
            match.group(2)
        )

        return (
            book_number,
            chunk_number
        )

    return (
        999999,
        999999
    )


# =========================================================
# LOAD EXISTING OUTPUT
# =========================================================

def load_existing_output():

    if not os.path.exists(
        OUTPUT_FILE
    ):
        return None

    try:

        with open(
            OUTPUT_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        return data

    except Exception as e:

        print()
        print(
            "WARNING: Existing output file "
            "could not be loaded."
        )

        print(e)

        return None


# =========================================================
# SAVE COMPLETE JSON
# =========================================================

def save_output(
    metadata,
    total_chunks,
    claims
):

    output_data = {

        "book_metadata": metadata,

        "claims": claims
    }

    # -----------------------------------------------------
    # Write to temporary file first
    # -----------------------------------------------------

    temp_file = (
        OUTPUT_FILE +
        ".tmp"
    )

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            output_data,
            f,
            ensure_ascii=False,
            indent=2
        )

    # -----------------------------------------------------
    # Replace existing output
    # -----------------------------------------------------

    os.replace(
        temp_file,
        OUTPUT_FILE
    )


# =========================================================
# MAIN PROCESS
# =========================================================

def process_book():

    # -----------------------------------------------------
    # Find chunks
    # -----------------------------------------------------

    chunk_files = glob.glob(
        os.path.join(
            CHUNK_FOLDER,
            "chunk_*.txt"
        )
    )

    # Numeric sorting
    chunk_files.sort(
        key=chunk_sort_key
    )

    total_chunks = len(
        chunk_files
    )

    if not chunk_files:

        print(
            f"No chunk files found in:"
        )

        print(
            CHUNK_FOLDER
        )

        return

    print()
    print("=" * 70)
    print(
        f"Found {total_chunks} chunks."
    )
    print("=" * 70)

    # -----------------------------------------------------
    # Check existing output
    # -----------------------------------------------------

    existing_data = (
        load_existing_output()
    )

    if existing_data:

        print()
        print(
            "Existing output found."
        )

        # ---------------------------------------------
        # Use existing metadata
        # ---------------------------------------------

        metadata = existing_data.get(
            "book_metadata",
            {}
        )

        # ---------------------------------------------
        # Use existing claims
        # ---------------------------------------------

        all_claims = existing_data.get(
            "claims",
            []
        )

        # ---------------------------------------------
        # Determine successfully processed chunks
        # ---------------------------------------------

        processed_chunks = set()

        for claim in all_claims:

            chunk_id = claim.get(
                "chunk_id"
            )

            if chunk_id:
                processed_chunks.add(
                    chunk_id
                )

        print(
            f"Existing claims: "
            f"{len(all_claims)}"
        )

        print(
            f"Already processed chunks: "
            f"{len(processed_chunks)}"
        )

    else:

        # ---------------------------------------------
        # No previous output
        # Extract metadata
        # ---------------------------------------------

        metadata = (
            extract_book_metadata()
        )

        all_claims = []

        processed_chunks = set()

        # Save initial metadata immediately
        save_output(
            metadata,
            total_chunks,
            all_claims
        )

        print()
        print(
            "Initial metadata saved."
        )

    # =====================================================
    # PROCESS CHUNKS
    # =====================================================

    for index, file_path in enumerate(
        chunk_files,
        start=1
    ):

        filename = os.path.basename(
            file_path
        )

        chunk_id = os.path.splitext(
            filename
        )[0]

        # -------------------------------------------------
        # Skip successfully processed chunks
        # -------------------------------------------------

        if chunk_id in processed_chunks:

            print()
            print(
                f"[{index}/{total_chunks}] "
                f"Skipping {filename} "
                f"(already processed)"
            )

            continue

        # -------------------------------------------------
        # Progress
        # -------------------------------------------------

        print()
        print("=" * 70)

        print(
            f"Processing "
            f"[{index}/{total_chunks}]"
        )

        print(
            f"File: {filename}"
        )

        print(
            f"Chunk ID: {chunk_id}"
        )

        # -------------------------------------------------
        # Read chunk
        # -------------------------------------------------

        try:

            with open(
                file_path,
                "r",
                encoding="utf-8"
            ) as f:

                text_content = f.read()

        except Exception as e:

            print(
                f"ERROR reading {filename}:"
            )

            print(e)

            continue

        word_count = len(
            text_content.split()
        )

        print(
            f"Words: {word_count}"
        )

        print(
            "Sending to Qwen..."
        )

        # -------------------------------------------------
        # Extract claims
        # -------------------------------------------------

        extracted_claims = (
            extract_claims_from_chunk(
                text_content,
                chunk_id
            )
        )

        # -------------------------------------------------
        # If extraction failed
        # -------------------------------------------------

        if extracted_claims is None:

            print()
            print(
                f"FAILED: {chunk_id}"
            )

            print(
                "This chunk will NOT be marked "
                "as processed."
            )

            print(
                "Run the script again to retry it."
            )

            continue

        # -------------------------------------------------
        # Add metadata to every claim
        # -------------------------------------------------

        for claim in extracted_claims:

            claim["chunk_id"] = (
                chunk_id
            )

            claim["source_file"] = (
                filename
            )

            all_claims.append(
                claim
            )

        # -------------------------------------------------
        # Mark as successfully processed
        # -------------------------------------------------

        processed_chunks.add(
            chunk_id
        )

        # -------------------------------------------------
        # Save after EVERY chunk
        # -------------------------------------------------

        save_output(
            metadata,
            total_chunks,
            all_claims
        )

        print()
        print(
            f"Claims extracted: "
            f"{len(extracted_claims)}"
        )

        print(
            f"Total claims so far: "
            f"{len(all_claims)}"
        )

        print(
            "Progress saved."
        )

    # =====================================================
    # COMPLETE
    # =====================================================

    print()
    print("=" * 70)
    print("PROCESSING COMPLETE")
    print("=" * 70)

    print(
        f"Total chunks: "
        f"{total_chunks}"
    )

    print(
        f"Successfully processed: "
        f"{len(processed_chunks)}"
    )

    print(
        f"Total claims: "
        f"{len(all_claims)}"
    )

    print()
    print(
        "Output:"
    )

    print(
        OUTPUT_FILE
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    process_book()
