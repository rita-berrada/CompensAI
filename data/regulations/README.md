Place full regulation texts here as plain UTF-8 `.txt` files.

Expected filenames:
- `eu261_2004.txt`
- `rail_2021_782.txt`
- `bus_181_2011.txt`
- `sea_1177_2010.txt`
- `consumer_2011_83.txt`
- `package_2015_2302.txt`

The lexical retriever splits by headings like `Article 5`, `Article 18`, `Chapter ...`, etc., indexes sections with SQLite FTS, and retrieves relevant sections without embeddings.

Current files in this folder are starter excerpts for demo/testing.
For hackathon demo quality, replace them with full consolidated legal text from official sources.
