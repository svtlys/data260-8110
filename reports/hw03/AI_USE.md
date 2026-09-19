# AI Use — HW3

1. **What I used an AI assistant for, and what I did myself:**

I used Claude to help scaffold the FastAPI auth router, walk through the Starlette session
cookie/timeout debugging, find real public source documents for my corpus, and set up the
three LlamaIndex chunking pipelines. I wrote and debugged the actual HTML templates myself
learning HTML from scratch, ran and troubleshot every curl/server test myself, and made the
calls on which corpus documents to use and how to interpret the retrieval results. Claude also assisted in creating the verify_hw03.py file.

2. **One AI-produced output that was wrong/unsuitable, or one thing I independently verified:**

My first attempt at scraping the San Jose city pages for the corpus produced files with only
~270 bytes of content instead of the real page text, because those pages are JavaScript-rendered
and plain curl only grabbed an empty shell. I independently verified this by checking file sizes
with ls -la before assuming the scrape had worked.

3. **How I detected the problem or verified the result:**

I noticed the file sizes were suspiciously tiny (258 and 272 bytes) compared to what a real page
of ordinance text should be, and confirmed by cat-ing the files and seeing they were essentially
empty.

4. **What I changed and why it works now:**

I re-fetched the actual rendered page content through a different method and manually verified
the corrected files were multiple KB with real, readable ordinance text before regenerating the
CORPUS_MANIFEST.json hashes against the corrected files.