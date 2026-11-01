import pandas as pd

# Load your original CSV file
df = pd.read_csv('a4tech_products.csv')

# Define the number of rows per file
rows_per_file = 16

# Loop to split and save the files
for i in range(0, len(df), rows_per_file):
    chunk = df.iloc[i:i + rows_per_file]
    file_number = (i // rows_per_file) + 1
    chunk.to_csv(f'a4tech_{file_number}.csv', index=False)
