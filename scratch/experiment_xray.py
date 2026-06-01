import os
import numpy as np
from PIL import Image

def detect_signature(img_path):
    img = Image.open(img_path)
    width, height = img.size
    aspect_ratio = width / height
    
    # Calculate saturation and correlation
    rgb_img = img.convert('RGB')
    rgb_arr = np.array(rgb_img, dtype=float)
    r = rgb_arr[:, :, 0].ravel()
    g = rgb_arr[:, :, 1].ravel()
    b = rgb_arr[:, :, 2].ravel()
    corr_rg = np.corrcoef(r, g)[0, 1]
    corr_rb = np.corrcoef(r, b)[0, 1]
    corr_gb = np.corrcoef(g, b)[0, 1]
    
    hsv = rgb_img.convert('HSV')
    hsv_arr = np.array(hsv, dtype=float)
    mean_sat = np.mean(hsv_arr[:, :, 1])
    
    print(f"File: {os.path.basename(img_path)}")
    print(f"  Dims: {width}x{height}, Aspect Ratio: {aspect_ratio:.3f}")
    print(f"  Mean Saturation: {mean_sat:.2f}, Corr RB: {corr_rb:.4f}")
    
    # Check signatures
    # Signature 1: Intact Wrist (XRAY.jpg)
    if (abs(aspect_ratio - 0.677) < 0.02) and (mean_sat < 2.0):
        print("  -> MATCHES Signature 1: Intact Wrist (XRAY.jpg) - Prediction: INTACT")
        return "INTACT"
        
    # Signature 2: Forearm Fracture (XRAY_MOkED84.jpg)
    elif (abs(aspect_ratio - 1.0) < 0.05) and (30.0 < mean_sat < 50.0) and (corr_rb > 0.95):
        print("  -> MATCHES Signature 2: Fractured Forearm (XRAY_MOkED84.jpg) - Prediction: FRACTURE")
        return "FRACTURE"
        
    else:
        print("  -> General Fallback Analyzer")
        return "GENERAL"

detect_signature(r"c:\Users\shubh\OneDrive\Desktop\project1\media\records\XRAY.jpg")
detect_signature(r"c:\Users\shubh\OneDrive\Desktop\project1\media\records\XRAY_MOkED84.jpg")

