import zipfile
import os

# The path you provided
zip_path = r'D:\drive-download-20260320T105048Z-1-001.zip'
# Where you want the files to end up
output_dir = r'D:\Sorted_Drive_Data'

def analyze_and_sort():
    if not os.path.exists(zip_path):
        print(f"Error: Could not find the file at {zip_path}")
        return

    print("🚀 Unzipping and analyzing... this might take a minute.")
    
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        # Get a list of all files in the ZIP
        file_list = zip_ref.namelist()
        
        # Create the output directory
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        print(f"✅ Found {len(file_list)} files. Sorting them now...")

        for file in file_list:
            # Skip folders themselves
            if file.endswith('/'):
                continue
            
            # Basic Logic: Change these keywords based on your life!
            work_keywords = ['invoice', 'project', 'client', 'meeting', 'q1', 'q2', 'contract']
            personal_keywords = ['photo', 'vacation', 'recipe', 'lease', 'wedding', 'medical']

            filename_lower = file.lower()
            
            if any(k in filename_lower for k in work_keywords):
                category = "Work"
            elif any(k in filename_lower for k in personal_keywords):
                category = "Personal"
            else:
                category = "Unsorted"

            # Create category folder
            target_path = os.path.join(output_dir, category)
            if not os.path.exists(target_path):
                os.makedirs(target_path)

            # Extract the file to the new home
            zip_ref.extract(file, target_path)

    print(f"✨ Done! Check your D: drive for a folder called 'Sorted_Drive_Data'.")

if __name__ == "__main__":
    analyze_and_sort()