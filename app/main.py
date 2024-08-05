import sys
import os
import time
import threading
import tempfile
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import List
from fastapi.middleware.cors import CORSMiddleware
from Data_extractor_V5 import Web2PDF, Web2Text, All2PDF
from tempfile import NamedTemporaryFile
import uuid
import logging
from PyPDF2 import PdfMerger

# Ensure the parent directory is in the sys.path for absolute imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Set up logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

app = FastAPI()

# To allow CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Define a Pydantic model to validate the input data
class URLList(BaseModel):
    urls: List[str]

# Serve static files (like CSS, JS, images)
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")

# Set up Jinja2 templates
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

def delete_file(file_path: str):
    try:
        os.remove(file_path)
        logging.info(f"Deleted file: {file_path}")
    except Exception as e:
        logging.error(f"Error deleting file {file_path}: {str(e)}")

# Global variable to signal stopping the process
stop_signal = threading.Event()

@app.post("/stop")
async def stop_processing():
    stop_signal.set()
    return {"message": "Processing stopped"}

@app.post("/web2pdf")
async def create_pdf(urls: URLList, background_tasks: BackgroundTasks):
    start_time = time.time()
    stop_signal.clear()
    try:
        # Create PDF files from the provided URLs
        web2pdf = Web2PDF(urls.urls)
        pdf_files = []
        for pdf_file in web2pdf.run():
            if stop_signal.is_set():
                break
            pdf_files.append(pdf_file)

        if not pdf_files:
            raise HTTPException(status_code=500, detail="Failed to generate PDFs")

        end_time = time.time()
        processing_time = end_time - start_time
        logging.info(f"Processing time for /web2pdf: {processing_time} seconds")

        # Schedule file deletion after response is sent
        for pdf_file in pdf_files:
            background_tasks.add_task(delete_file, pdf_file)

        # Return the first PDF file for simplicity
        # Modify this part if you want to handle multiple PDFs differently
        return FileResponse(pdf_files[0], media_type='application/pdf', filename=os.path.basename(pdf_files[0]), headers={
            "X-Processing-Time": str(processing_time)
        })
    except Exception as e:
        logging.error(f"Error in /web2pdf endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/web2text/")
async def web2text(url_list: URLList):
    web2text = Web2Text(url_list.urls)
    text_pdf_paths = web2text.run()
    if not text_pdf_paths:
        raise HTTPException(status_code=500, detail="Failed to extract text and convert to PDFs")

    if len(text_pdf_paths) > 1:
        with NamedTemporaryFile(delete=False, suffix=".pdf") as temp_merged_pdf:
            merger = PdfMerger()
            for pdf_path in text_pdf_paths:
                merger.append(pdf_path)
            merger.write(temp_merged_pdf.name)
            merger.close()
            temp_merged_pdf_path = temp_merged_pdf.name

        return FileResponse(temp_merged_pdf_path, media_type="application/pdf", filename="merged_text_output.pdf")
    elif len(text_pdf_paths) == 1:
        return FileResponse(text_pdf_paths[0], media_type="application/pdf", filename=os.path.basename(text_pdf_paths[0]))
    else:
        raise HTTPException(status_code=500, detail="No PDFs generated")
        
@app.post("/all2pdf")
async def generate_all_pdfs(urls: URLList, background_tasks: BackgroundTasks):
    start_time = time.time()
    try:
        # Process the provided URLs to generate PDFs
        all2pdf = All2PDF(urls.urls)
        pdf_paths = []
        for pdf_path in all2pdf.run():
            pdf_paths.append(pdf_path)

        # Merge PDFs
        merged_pdf_path = all2pdf.merge_pdfs(pdf_paths)

        # Extract URLs from the merged PDF
        df_urls = all2pdf.extract_urls_from_pdf(merged_pdf_path)

        # Save URLs to a CSV file in a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as temp_csv:
            df_urls.to_csv(temp_csv.name, index=False)
            csv_path = temp_csv.name

        # Save all linked pages as PDFs
        linked_pdf_paths = []
        for linked_pdf_path in all2pdf.save_all_linked_pages_as_pdfs(df_urls):
            linked_pdf_paths.append(linked_pdf_path)

        # Combine all PDF paths and CSV path
        all_file_paths = pdf_paths + linked_pdf_paths + [csv_path]

        # Create a zip file containing all PDFs and the CSV
        zip_file_path = all2pdf.create_zip_file(all_file_paths)

        # Schedule file deletion after response is sent
        background_tasks.add_task(delete_file, zip_file_path)

        # Also schedule deletion of temporary CSV and PDF files
        for file_path in all_file_paths:
            background_tasks.add_task(delete_file, file_path)

        end_time = time.time()
        processing_time = end_time - start_time
        logging.info(f"Processing time for /all2pdf: {processing_time} seconds")

        return FileResponse(zip_file_path, media_type='application/zip', filename="output.zip", headers={
            "X-Processing-Time": str(processing_time)
        })
    except Exception as e:
        logging.error(f"Error in /all2pdf endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# You can run this FastAPI app using an ASGI server like uvicorn
# Example command: uvicorn main:app --reload