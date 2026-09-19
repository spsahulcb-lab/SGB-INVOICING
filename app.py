import google.generativeai as genai
import PIL.Image

def extract_bill_data_with_gemini3(image_file=None, raw_text=None):
    # Gemini 3 Flash Model Integration
    model = genai.GenerativeModel('gemini-3-flash-preview')
    
    prompt = """
    You are an expert pharma billing OCR system. 
    Extract party_name, products (name, qty, rate, amount) from this bill image/text.
    Return ONLY a valid JSON format like:
    {
      "party_name": "Name",
      "items": [
        {"product_name": "ATPLEX Syrup", "qty": 10, "rate": 120}
      ]
    }
    """
    
    if image_file:
        img = PIL.Image.open(image_file)
        response = model.generate_content([prompt, img])
    else:
        response = model.generate_content([prompt, raw_text])
        
    return response.text
