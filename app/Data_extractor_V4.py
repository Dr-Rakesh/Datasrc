import os
import time
import base64
import logging
import pandas as pd
import fitz
import zipfile
import tempfile
import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from PyPDF2 import PdfMerger
from urllib3.exceptions import MaxRetryError, NewConnectionError
from concurrent.futures import ThreadPoolExecutor, as_completed
from selenium.common.exceptions import TimeoutException
from bs4 import BeautifulSoup
from fpdf import FPDF

class Web2PDF:
    def __init__(self, urls):
        self.logger = logging.getLogger("Web2PDF")
        logging.basicConfig(level=logging.DEBUG)
        self.urls = [
            f"http://{url.strip()}" if not url.startswith("http") else url.strip()
            for url in urls
        ]
        self.logger.debug(f"Initialized with URLs: {self.urls}")
        self.driver = self._setup_driver()

    def _setup_driver(self):
        self.logger.debug("Setting up Chrome driver")
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        driver = webdriver.Chrome(
            service=ChromeService(), options=chrome_options
        )
        self.logger.debug("Chrome driver setup complete")
        return driver

    def save_page_as_pdf(self, url, base_filename):
        retry_attempts = 3
        for attempt in range(retry_attempts):
            driver = self._setup_driver()
            try:
                self.logger.debug(f"Saving {url} to PDF as {base_filename}")
                driver.get(url)
                time.sleep(5)  # Wait for the page to load

                # Try to dismiss the cookie consent pop-up
                try:
                    wait = WebDriverWait(driver, 10)
                    consent_button = wait.until(
                        EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Accept')]"))
                    )
                    consent_button.click()
                    self.logger.debug("Dismissed cookie consent pop-up")
                except Exception as e:
                    self.logger.warning(f"No cookie consent pop-up found or could not be dismissed: {e}")

                time.sleep(5)  # Additional wait time to ensure pop-up is dismissed

                print_options = {
                    "landscape": False,
                    "displayHeaderFooter": False,
                    "printBackground": True,
                    "preferCSSPageSize": True,
                }

                result = driver.execute_cdp_cmd("Page.printToPDF", print_options)
                pdf_data = base64.b64decode(result["data"])

                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
                    temp_pdf.write(pdf_data)
                    temp_pdf_path = temp_pdf.name

                self.logger.debug(f"Saved PDF to temporary file: {temp_pdf_path}")
                return temp_pdf_path
            except MaxRetryError as e:
                self.logger.error(f"MaxRetryError on attempt {attempt + 1}: {e}")
            except NewConnectionError as e:
                self.logger.error(f"NewConnectionError on attempt {attempt + 1}: {e}")
            except Exception as e:
                self.logger.error(f"Error on attempt {attempt + 1}: {e}")
            finally:
                driver.quit()
                time.sleep(5)  # Wait before retrying
        self.logger.error(f"Failed to save {url} after {retry_attempts} attempts")
        return None

    def run(self):
        self.logger.debug("Running Web2PDF process")
        pdf_file_paths = []
        with ThreadPoolExecutor(max_workers=4) as executor:  # Adjust max_workers based on your system capabilities
            futures = {executor.submit(self.save_page_as_pdf, url, f"output_{i + 1}"): url for i, url in enumerate(self.urls)}
            for future in as_completed(futures):
                url = futures[future]
                try:
                    pdf_file_path = future.result()
                    if pdf_file_path:
                        pdf_file_paths.append(pdf_file_path)
                except Exception as e:
                    self.logger.error(f"Error processing URL {url}: {e}")
        self.logger.debug("Web2PDF process complete")
        return pdf_file_paths

class Web2Text:
    def __init__(self, urls=None):
        self.logger = logging.getLogger("Web2Text")
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        if urls:
            self.urls = [
                f"http://{url.strip()}" if not url.startswith("http") else url.strip()
                for url in urls
            ]
        else:
            self.urls = []
        self.logger.debug(f"Initialized with URLs: {self.urls}")

    def _setup_driver(self):
        self.logger.debug("Setting up Chrome driver")
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        driver = webdriver.Chrome(
            service=ChromeService(), options=chrome_options
        )
        self.logger.debug("Chrome driver setup complete")
        return driver

    def extract_text_from_website(self, url, base_filename):
        retry_attempts = 3
        for attempt in range(retry_attempts):
            driver = self._setup_driver()
            try:
                self.logger.debug(f"Loading URL: {url}")
                driver.get(url)
                time.sleep(5)  # Wait for the page to load

                # Try to dismiss the cookie consent pop-up
                try:
                    wait = WebDriverWait(driver, 10)
                    consent_button = wait.until(
                        EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Accept')]"))
                    )
                    consent_button.click()
                    self.logger.debug("Dismissed cookie consent pop-up")
                except Exception as e:
                    self.logger.warning(f"No cookie consent pop-up found or could not be dismissed: {e}")

                time.sleep(5)  # Additional wait time to ensure pop-up is dismissed

                soup = BeautifulSoup(driver.page_source, "html.parser")
                paragraphs = soup.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "span", "div"])
                extracted_text = "\n\n".join([tag.get_text(strip=True) for tag in paragraphs])

                temp_pdf_path = self.save_text_to_temp_pdf(extracted_text)
                return temp_pdf_path

            except TimeoutException as e:
                self.logger.error(f"TimeoutException on attempt {attempt + 1}: {e}")
            except Exception as e:
                self.logger.error(f"Error on attempt {attempt + 1}: {e}")
            finally:
                driver.quit()
                time.sleep(5)  # Wait before retrying
        self.logger.error(f"Failed to save {url} after {retry_attempts} attempts")
        return None

    def save_text_to_temp_pdf(self, text):
        try:
            self.logger.debug("Saving text to a temporary PDF file")
            pdf = FPDF()
            pdf.add_page()
            pdf.set_auto_page_break(auto=True, margin=15)
            pdf.set_font("Arial", size=12)
            # Properly handle encoding by encoding text to 'latin-1'
            encoded_text = text.encode('latin-1', 'replace').decode('latin-1')
            pdf.multi_cell(0, 10, encoded_text)

            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
                pdf.output(temp_pdf.name, "F")
                temp_pdf_path = temp_pdf.name

            self.logger.debug(f"Saved PDF to temporary file: {temp_pdf_path}")
            return temp_pdf_path
        except Exception as e:
            self.logger.error(f"Error saving PDF to temporary file: {e}")
            return None

    def run(self):
        self.logger.debug("Running Web2Text process")
        pdf_file_paths = []
        with ThreadPoolExecutor(max_workers=4) as executor:  # Adjust max_workers based on your system capabilities
            futures = {executor.submit(self.extract_text_from_website, url, f"text_output_{i + 1}"): url for i, url in enumerate(self.urls)}
            for future in as_completed(futures):
                url = futures[future]
                try:
                    pdf_file_path = future.result()
                    if pdf_file_path:
                        pdf_file_paths.append(pdf_file_path)
                        self.logger.debug(f"Text PDF saved: {pdf_file_path}")
                    else:
                        self.logger.debug(f"Text PDF not saved for URL: {url}")
                except Exception as e:
                    self.logger.error(f"Error processing URL {url}: {e}")
        self.logger.debug("Web2Text process complete")
        return pdf_file_paths
    
class All2PDF:
    def __init__(self, urls):
        self.logger = logging.getLogger("All2PDF")
        logging.basicConfig(level=logging.DEBUG)
        self.urls = [
            f"http://{url.strip()}" if not url.startswith("http") else url.strip()
            for url in urls
        ]
        self.logger.debug(f"Initialized with URLs: {self.urls}")

    def _setup_driver(self):
        self.logger.debug("Setting up Chrome driver")
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        driver = webdriver.Chrome(
            service=ChromeService(), options=chrome_options
        )
        self.logger.debug("Chrome driver setup complete")
        return driver

    def save_page_as_pdf(self, url, base_filename):
        retry_attempts = 3
        for attempt in range(retry_attempts):
            driver = self._setup_driver()
            try:
                self.logger.debug(f"Saving {url} to PDF as {base_filename}")
                driver.get(url)
                time.sleep(5)  # Wait for the page to load

                # Try to dismiss the cookie consent pop-up
                try:
                    wait = WebDriverWait(driver, 10)
                    consent_button = wait.until(
                        EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Accept')]"))
                    )
                    consent_button.click()
                    self.logger.debug("Dismissed cookie consent pop-up")
                except Exception as e:
                    self.logger.warning(f"No cookie consent pop-up found or could not be dismissed: {e}")

                time.sleep(5)  # Additional wait time to ensure pop-up is dismissed

                print_options = {
                    "landscape": False,
                    "displayHeaderFooter": False,
                    "printBackground": True,
                    "preferCSSPageSize": True,
                }

                result = driver.execute_cdp_cmd("Page.printToPDF", print_options)
                pdf_data = base64.b64decode(result["data"])

                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
                    temp_pdf.write(pdf_data)
                    temp_pdf_path = temp_pdf.name

                self.logger.debug(f"Saved PDF to temporary file: {temp_pdf_path}")
                return temp_pdf_path
            except TimeoutException as e:
                self.logger.error(f"TimeoutException on attempt {attempt + 1}: {e}")
            except Exception as e:
                self.logger.error(f"Error on attempt {attempt + 1}: {e}")
            finally:
                driver.quit()
                time.sleep(5)  # Wait before retrying
        self.logger.error(f"Failed to save {url} after {retry_attempts} attempts")
        return None

    def run(self):
        self.logger.debug("Running All2PDF process")
        pdf_file_paths = []
        with ThreadPoolExecutor(max_workers=4) as executor:  # Adjust max_workers based on your system capabilities
            futures = {executor.submit(self.save_page_as_pdf, url, f"output_{i + 1}"): url for i, url in enumerate(self.urls)}
            for future in as_completed(futures):
                url = futures[future]
                try:
                    pdf_file_path = future.result()
                    if pdf_file_path:
                        pdf_file_paths.append(pdf_file_path)
                except Exception as e:
                    self.logger.error(f"Error processing URL {url}: {e}")
        self.logger.debug("All2PDF process complete")
        return pdf_file_paths

    def merge_pdfs(self, pdf_paths):
        self.logger.debug("Merging PDFs")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_merged_pdf:
            merger = PdfMerger()
            for pdf in pdf_paths:
                merger.append(pdf)
            merger.write(temp_merged_pdf.name)
            merger.close()
            temp_merged_pdf_path = temp_merged_pdf.name
        self.logger.debug(f"Merged PDF saved at: {temp_merged_pdf_path}")
        return temp_merged_pdf_path

    def extract_urls_from_pdf(self, pdf_path):
        # Open the PDF file
        document = fitz.open(pdf_path)
        urls = []

        # Iterate through each page
        for page_num in range(len(document)):
            page = document[page_num]
            links = page.get_links()

            # Extract clickable URLs
            for link in links:
                if link['uri']:
                    urls.append({
                        'page_num': page_num + 1,
                        'uri': link['uri']
                    })

        # Create a pandas DataFrame
        df = pd.DataFrame(urls)
        return df

    def save_all_linked_pages_as_pdfs(self, df_urls):
        self.logger.debug("Saving all linked pages as PDFs")
        pdf_file_paths = []
        with ThreadPoolExecutor(max_workers=4) as executor:  # Adjust max_workers based on your system capabilities
            futures = {executor.submit(self.save_page_as_pdf, row['uri'], f"linked_output_{i + 1}"): row['uri'] for i, row in df_urls.iterrows()}
            for future in as_completed(futures):
                url = futures[future]
                try:
                    pdf_file_path = future.result()
                    if pdf_file_path:
                        pdf_file_paths.append(pdf_file_path)
                except Exception as e:
                    self.logger.error(f"Error processing linked URL {url}: {e}")
        self.logger.debug("Saved all linked pages as PDFs")
        return pdf_file_paths

    def create_zip_file(self, file_paths, zip_filename="output.zip"):
        self.logger.debug("Creating zip file")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as temp_zip:
            with zipfile.ZipFile(temp_zip.name, 'w') as zipf:
                for file in file_paths:
                    zipf.write(file, os.path.basename(file))
            temp_zip_path = temp_zip.name
        self.logger.debug(f"Zip file created at: {temp_zip_path}")
        return temp_zip_path