import os
import json
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.firefox import GeckoDriverManager
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options
import traceback
from concurrent.futures import ThreadPoolExecutor
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime

class AgiliteScraper:
    def __init__(self, test_mode=False):
        self.base_url = "https://agilite.co.il/collections/all"
        self.driver = None
        self.test_mode = test_mode
        self.setup_driver()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Firefox/123.0'
        })

    def setup_driver(self):
        try:
            print("Setting up Firefox driver...")
            firefox_options = Options()
            firefox_options.add_argument('--width=1920')
            firefox_options.add_argument('--height=1080')
            firefox_options.set_preference('permissions.default.image', 2)  # Disable image loading
            firefox_options.set_preference('dom.ipc.plugins.enabled.libflashplayer.so', False)  # Disable Flash
            firefox_options.add_argument('--no-sandbox')
            firefox_options.add_argument('--headless')
            
            # Add security preferences
            firefox_options.set_preference('security.ssl.enable_ocsp_stapling', False)
            firefox_options.set_preference('security.ssl.enable_false_start', False)
            firefox_options.set_preference('security.default_personal_cert', 'Select Automatically')
            firefox_options.set_preference('security.enterprise_roots.enabled', True)
            firefox_options.set_preference('security.enterprise_roots.auto-enabled', True)
            
            # Set user agent
            firefox_options.set_preference('general.useragent.override', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0')
            
            service = Service(GeckoDriverManager().install())
            self.driver = webdriver.Firefox(service=service, options=firefox_options)
            self.driver.set_page_load_timeout(30)  # Set page load timeout
            self.driver.implicitly_wait(5)  # Set implicit wait time
            print("Firefox driver setup completed successfully")
        except Exception as e:
            print(f"Error setting up Firefox driver: {str(e)}")
            print("Full traceback:")
            print(traceback.format_exc())
            raise

    def save_intermediate_data(self, data, filename):
        """Save intermediate data to JSON file"""
        try:
            if self.test_mode:
                directory = 'data/test_scrape'
            else:
                directory = 'data/raw'
            
            os.makedirs(directory, exist_ok=True)
            filepath = os.path.join(directory, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            print(f"Data saved to {filepath}")
        except Exception as e:
            print(f"Error saving intermediate data: {str(e)}")

    def get_total_pages(self):
        """Get total number of pages using Shopify pagination"""
        try:
            response = self.session.get(self.base_url)
            soup = BeautifulSoup(response.text, 'html.parser')
            # Shopify uses standard pagination class
            pagination = soup.find('div', class_='pagination')
            if pagination:
                # Find all page number links
                page_numbers = [int(a.text) for a in pagination.find_all('a') if a.text.isdigit()]
                total_pages = max(page_numbers) if page_numbers else 1
                
                # Save pagination data in test mode
                if self.test_mode:
                    self.save_intermediate_data({
                        'total_pages': total_pages,
                        'page_numbers': page_numbers,
                        'pagination_html': str(pagination)
                    }, 'pagination_data.json')
                
                return total_pages
            return 1
        except Exception as e:
            print(f"Error getting total pages: {str(e)}")
            return 1

    def get_product_links_from_page(self, page_url):
        """Get product links from a single page using Shopify structure"""
        try:
            response = self.session.get(page_url)
            soup = BeautifulSoup(response.text, 'html.parser')
            product_links = []
            
            # Shopify uses standard classes for product cards
            product_cards = soup.find_all('div', class_=lambda x: x and ('product-card' in x or 'grid-product' in x))
            
            for card in product_cards:
                # Find product link in the card
                link = card.find('a', href=re.compile(r'/products/'))
                if link:
                    product_url = link.get('href')
                    if product_url and '/products/' in product_url:
                        full_url = f"https://agilite.co.il{product_url}"
                        if full_url not in product_links:
                            product_links.append(full_url)
            
            # Save page data in test mode
            if self.test_mode:
                page_number = page_url.split('page=')[-1]
                self.save_intermediate_data({
                    'page_url': page_url,
                    'product_links': product_links,
                    'cards_found': len(product_cards),
                    'page_html': str(soup)
                }, f'page_{page_number}_data.json')
            
            return product_links
        except Exception as e:
            print(f"Error getting product links from page {page_url}: {str(e)}")
            return []

    def get_all_pagination_links(self):
        """Collect all real page links from the pagination block"""
        response = self.session.get(self.base_url)
        soup = BeautifulSoup(response.text, 'html.parser')
        pagination = soup.find('nav', class_='pagination')
        page_urls = set()
        if pagination:
            for a in pagination.find_all('a', href=True):
                href = a['href']
                if href.startswith('/'):
                    full_url = f"https://agilite.co.il{href}"
                else:
                    full_url = href
                page_urls.add(full_url)
        # Explicitly add the first page if it's not in pagination
        if self.base_url not in page_urls:
            page_urls.add(self.base_url)
        return sorted(page_urls)

    def get_product_links(self):
        """Get all product links from all pages (using real links from pagination)"""
        print("Getting product links...")
        all_links = []
        if self.test_mode:
            page_urls = [self.base_url]
            print("Test mode: Processing only first page")
        else:
            page_urls = self.get_all_pagination_links()
            print(f"Page URLs to process: {page_urls}")

        with ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(self.get_product_links_from_page, page_urls))

        for links in results:
            all_links.extend(links)

        print(f"Found {len(all_links)} product links")
        
        # Save all links in test mode
        if self.test_mode:
            self.save_intermediate_data({
                'total_links': len(all_links),
                'links': all_links
            }, 'all_product_links.json')
        
        return all_links

    def extract_json_ld_data(self, page_source):
        """Extract product data from JSON-LD structured data"""
        try:
            soup = BeautifulSoup(page_source, 'html.parser')
            json_ld_scripts = soup.find_all('script', type='application/ld+json')
            
            for script in json_ld_scripts:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict) and data.get('@type') == 'Product':
                        print(f"Found Product JSON-LD data: {data.get('name', 'Unknown')}")
                        return data
                    # Also check for arrays of products
                    elif isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and item.get('@type') == 'Product':
                                print(f"Found Product JSON-LD data in array: {item.get('name', 'Unknown')}")
                                return item
                except json.JSONDecodeError:
                    continue
            return None
        except Exception as e:
            print(f"Error extracting JSON-LD data: {str(e)}")
            return None

    def get_product_data(self, url):
        """Get product data using updated selectors based on HTML analysis"""
        try:
            print(f"\nProcessing product: {url}")
            
            # Clear cache and cookies in a safer way
            try:
                self.driver.delete_all_cookies()
            except Exception as e:
                print(f"Warning: Could not clear cookies: {str(e)}")
            
            # Navigate to URL with retry mechanism
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    print(f"Attempt {attempt + 1} to load {url}")
                    self.driver.get(url)
                    break
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    print(f"Attempt {attempt + 1} failed: {str(e)}")
                    time.sleep(2)
            
            # Wait for page to load and check URL
            wait = WebDriverWait(self.driver, 15)
            
            # Wait for the page to actually load the correct URL
            expected_product_handle = url.split('/')[-1]
            max_retries = 3
            for attempt in range(max_retries):
                time.sleep(2)  # Give page time to load
                current_url = self.driver.current_url
                current_handle = current_url.split('/')[-1].split('?')[0]
                
                if current_handle == expected_product_handle:
                    print(f"✓ Correct page loaded: {current_handle}")
                    break
                elif attempt < max_retries - 1:
                    print(f"⚠ Wrong page loaded ({current_handle}), retrying... (attempt {attempt + 1})")
                    self.driver.refresh()
                    time.sleep(3)
                else:
                    print(f"✗ Failed to load correct page after {max_retries} attempts")
                    return None
            
            # Additional wait for page content to load
            try:
                wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                time.sleep(2)  # Extra buffer for JS to execute
            except TimeoutException:
                print("Timeout waiting for page body to load")
                return None
            
            # Save page source for debugging
            if self.test_mode:
                product_id = url.split('/')[-1]
                page_source = self.driver.page_source
                with open(f'data/test_scrape/product_{product_id}_page.html', 'w', encoding='utf-8') as f:
                    f.write(page_source)
                print(f"Saved page source to product_{product_id}_page.html")
                
                # Verify we have the correct page by checking title
                soup = BeautifulSoup(page_source, 'html.parser')
                title = soup.find('title')
                if title:
                    print(f"Page title: {title.text.strip()}")

            # Initialize product data
            product_data = {
                'url': url,
                'title': None,
                'price': None,
                'variants': [],
                'description': None,
                'images': [],
                'stock_status': None,
                'timestamp': datetime.now().isoformat()
            }

            # Extract JSON-LD data first
            json_ld_data = self.extract_json_ld_data(self.driver.page_source)
            if json_ld_data:
                print("Found JSON-LD structured data")
                
                # Get basic info from JSON-LD
                product_data['title'] = json_ld_data.get('name')
                product_data['description'] = json_ld_data.get('description', '').replace('\n', ' ').strip()
                
                # Get images from JSON-LD
                if 'image' in json_ld_data:
                    image_data = json_ld_data['image']
                    if isinstance(image_data, dict):
                        product_data['images'] = [image_data.get('url', '')]
                    elif isinstance(image_data, list):
                        product_data['images'] = [img.get('url', '') if isinstance(img, dict) else str(img) for img in image_data]
                    else:
                        product_data['images'] = [str(image_data)]
                
                # Get variants and stock status from JSON-LD offers
                if 'offers' in json_ld_data:
                    offers = json_ld_data['offers']
                    if isinstance(offers, list):
                        variant_names = [offer.get('name') for offer in offers if offer.get('name')]
                        if variant_names:
                             product_data['variants'].append({'type': 'General', 'values': variant_names})

                        for offer in offers:
                            # Get price from first offer
                            if not product_data['price'] and 'price' in offer:
                                product_data['price'] = str(offer['price'])
                            # Get availability
                            if 'availability' in offer:
                                product_data['stock_status'] = offer['availability']
                    elif isinstance(offers, dict):
                        if 'name' in offers:
                            product_data['variants'].append({'type': 'General', 'values': [offers['name']]})
                        if 'price' in offers:
                            product_data['price'] = str(offers['price'])
                        if 'availability' in offers:
                            product_data['stock_status'] = offers['availability']

            # Fallback to HTML selectors if JSON-LD didn't provide all data
            
            # Get product title if not found in JSON-LD
            if not product_data['title']:
                try:
                    print("Looking for product title in HTML...")
                    title_element = wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, 'h2.product-title, h1.product-title, .product-title'))
                    )
                    product_data['title'] = title_element.text.strip()
                    print(f"Found title: {product_data['title']}")
                except Exception as e:
                    print(f"Error getting title from HTML: {str(e)}")

            # Get price if not found in JSON-LD
            if not product_data['price']:
                try:
                    print("Looking for price in HTML...")
                    # Try different price selectors based on HTML structure
                    price_selectors = [
                        'sale-price',
                        '.price-list sale-price',
                        '.price',
                        '.product-price',
                        '[class*="price"]'
                    ]
                    
                    for selector in price_selectors:
                        try:
                            price_element = wait.until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                            )
                            price_text = price_element.text.strip()
                            # Clean up price text - remove currency symbol and extra spaces
                            price_text = re.sub(r'[^\d.,]', '', price_text)
                            if price_text:
                                product_data['price'] = price_text
                                print(f"Found price with selector {selector}: {product_data['price']}")
                                break
                        except:
                            continue
                except Exception as e:
                    print(f"Error getting price from HTML: {str(e)}")

            # Get variants if not found in JSON-LD
            if not product_data['variants']:
                try:
                    print("Looking for variants in HTML...")
                    # Selector for variant groups (fieldset, etc.)
                    variant_group_selectors = [
                        '.product-form__input',
                        '.selector-wrapper',
                        '.variant-picker',
                        '.product-form__option'
                    ]

                    for group_selector in variant_group_selectors:
                        try:
                            variant_groups = self.driver.find_elements(By.CSS_SELECTOR, group_selector)
                            if not variant_groups:
                                continue

                            print(f"Found {len(variant_groups)} variant groups with selector '{group_selector}'")
                            for group in variant_groups:
                                try:
                                    # Find the title of the variant group (e.g., "Color", "Size")
                                    group_title_element = group.find_element(By.CSS_SELECTOR, 'label, .form__label, .variant__label')
                                    group_title = group_title_element.text.strip().replace(':', '')
                                except NoSuchElementException:
                                    group_title = "Unknown"
                                
                                # Find all values within this group
                                value_elements = group.find_elements(By.CSS_SELECTOR, 'input[type="radio"], option, [data-value]')
                                values = []

                                if not value_elements: # Fallback for different structures
                                     value_elements = group.find_elements(By.CSS_SELECTOR, '.variant-input-wrap')

                                for el in value_elements:
                                    value = None
                                    if el.tag_name == 'input':
                                        value = el.get_attribute('value')
                                    elif el.tag_name == 'option':
                                        value = el.text.strip()
                                        if "select" in value.lower(): continue # Skip placeholder
                                    else: # Other elements like divs or custom tags
                                        value = el.get_attribute('data-value') or el.text.strip()
                                    
                                    if value and value not in values:
                                        values.append(value)
                                
                                if values:
                                    # Check if this group is already added
                                    is_new_group = True
                                    for existing_group in product_data['variants']:
                                        if existing_group['type'] == group_title:
                                            is_new_group = False
                                            # Add new values if any
                                            for v in values:
                                                if v not in existing_group['values']:
                                                    existing_group['values'].append(v)
                                            break
                                    if is_new_group:
                                         product_data['variants'].append({
                                            'type': group_title,
                                            'values': values
                                        })
                                    print(f"Found variant group '{group_title}' with values: {values}")
                                
                            # If we found variants with this group selector, we can stop
                            if product_data['variants']:
                                break 
                        except Exception as e:
                            print(f"Error processing group selector {group_selector}: {e}")
                            continue

                except Exception as e:
                    print(f"Error getting variants from HTML: {str(e)}")

            # Get images if not found in JSON-LD
            if not product_data['images']:
                try:
                    print("Looking for images in HTML...")
                    # Try different image selectors
                    image_selectors = [
                        '.product-single__photos img',
                        '.product-gallery img',
                        '.product-images img',
                        '[class*="product"] img'
                    ]
                    
                    for selector in image_selectors:
                        try:
                            image_elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                            product_data['images'] = [img.get_attribute('src') for img in image_elements if img.get_attribute('src')]
                            if product_data['images']:
                                print(f"Found {len(product_data['images'])} images with selector {selector}")
                                break
                        except:
                            continue
                except Exception as e:
                    print(f"Error getting images from HTML: {str(e)}")

            # Get stock status if not found in JSON-LD
            if not product_data['stock_status']:
                try:
                    print("Looking for stock status in HTML...")
                    # Try different stock status selectors - more specific ones first
                    stock_selectors = [
                        '.product-inventory',
                        '.stock-status',
                        '.availability',
                        '[class*="stock"]',
                        '[class*="inventory"]',
                        '[class*="availability"]',
                        '.add-to-cart-button',
                        '.product-form__submit',
                        'button[type="submit"]'
                    ]
                    
                    for selector in stock_selectors:
                        try:
                            stock_elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                            if not stock_elements:
                                continue
                                
                            for stock_element in stock_elements:
                                stock_text = stock_element.text.strip().lower()
                                element_class = stock_element.get_attribute('class') or ''
                                element_disabled = stock_element.get_attribute('disabled')
                                
                                print(f"Checking stock element: '{stock_text}' (class: {element_class}, disabled: {element_disabled})")
                                
                                # Check for common stock status indicators
                                if ('out of stock' in stock_text or 'sold out' in stock_text or 
                                    'unavailable' in stock_text or 'not available' in stock_text):
                                    product_data['stock_status'] = 'Out of Stock'
                                    print(f"Found stock status: {product_data['stock_status']}")
                                    break
                                elif ('in stock' in stock_text or 'available' in stock_text or 
                                      'add to cart' in stock_text or 'buy now' in stock_text):
                                    # Additional check: if button is disabled, it might be out of stock
                                    if element_disabled:
                                        product_data['stock_status'] = 'Out of Stock'
                                    else:
                                        product_data['stock_status'] = 'In Stock'
                                    print(f"Found stock status: {product_data['stock_status']}")
                                    break
                                elif 'pre-order' in stock_text:
                                    product_data['stock_status'] = 'Pre-order'
                                    print(f"Found stock status: {product_data['stock_status']}")
                                    break
                            
                            if product_data['stock_status']:
                                break
                        except Exception as e:
                            print(f"Error checking selector {selector}: {str(e)}")
                            continue
                            
                    # If still no stock status found, try to infer from page structure
                    if not product_data['stock_status']:
                        print("Trying to infer stock status from page structure...")
                        try:
                            # Check if there's a disabled add to cart button
                            disabled_buttons = self.driver.find_elements(By.CSS_SELECTOR, 'button[disabled], input[disabled]')
                            if disabled_buttons:
                                for button in disabled_buttons:
                                    button_text = button.text.strip().lower()
                                    if any(word in button_text for word in ['add to cart', 'buy', 'purchase']):
                                        product_data['stock_status'] = 'Out of Stock'
                                        print(f"Inferred stock status from disabled button: {product_data['stock_status']}")
                                        break
                            
                            # If still no status, assume in stock if we found a price
                            if not product_data['stock_status'] and product_data['price']:
                                product_data['stock_status'] = 'In Stock'
                                print(f"Assuming in stock based on price presence: {product_data['stock_status']}")
                                
                        except Exception as e:
                            print(f"Error inferring stock status: {str(e)}")
                            
                except Exception as e:
                    print(f"Error getting stock status from HTML: {str(e)}")

            # Save product data in test mode
            if self.test_mode:
                product_id = url.split('/')[-1]
                self.save_intermediate_data(product_data, f'product_{product_id}_data.json')

            print(f"✓ Successfully processed: {product_data['title']}")
            return product_data
        except Exception as e:
            print(f"Error getting product data from {url}: {str(e)}")
            print("Full traceback:")
            print(traceback.format_exc())
            return None

    def scrape_all_products(self):
        """Scrape data for all products"""
        print("Starting product scraping...")
        product_links = self.get_product_links()
        products = []
        
        # In test mode, only process first few products
        if self.test_mode:
            product_links = product_links[:3]
            print("Test mode: Processing only first 3 products")

        # Process products sequentially to avoid cache issues
        # No threading for now to ensure clean page loads
        results = []
        for i, url in enumerate(product_links):
            print(f"\n{'='*50}")
            print(f"Processing product {i+1}/{len(product_links)}")
            print(f"{'='*50}")
            
            result = self.get_product_data(url)
            results.append(result)
            
            # Add delay between products to ensure clean separation
            if i < len(product_links) - 1:  # Don't sleep after last product
                print("Waiting 3 seconds before next product...")
                time.sleep(3)
        
        products = [p for p in results if p is not None]
        
        print(f"Successfully scraped {len(products)} products")
        return products

    def save_products_data(self, products):
        """Save product data to JSON file"""
        try:
            if self.test_mode:
                directory = 'data/test_scrape'
            else:
                directory = 'data/raw'
            
            os.makedirs(directory, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f'products_{timestamp}.json'
            filepath = os.path.join(directory, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(products, f, ensure_ascii=False, indent=2)
            
            print(f"Data saved to {filepath}")
        except Exception as e:
            print(f"Error saving data: {str(e)}")

    def close(self):
        """Close the browser"""
        if self.driver:
            self.driver.quit()

if __name__ == "__main__":
    try:
        # Create scraper in normal mode
        scraper = AgiliteScraper(test_mode=False)
        products = scraper.scrape_all_products()
        scraper.save_products_data(products)
    except Exception as e:
        print(f"Error during scraping: {str(e)}")
        print("Full traceback:")
        print(traceback.format_exc())
    finally:
        if 'scraper' in locals():
            scraper.close() 