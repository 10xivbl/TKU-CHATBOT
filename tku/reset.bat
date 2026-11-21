@echo off
del /q seen.db data\failed_urls.txt data\due_urls.txt data\crawl_results_*.jsonl data\skipped_pdfs.txt 2>nul
rmdir /s /q data\export 2>nul
rmdir /s /q data\scanned_pdfs 2>nul
rmdir /s /q logs 2>nul
echo Reset done.
