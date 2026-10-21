import pandas as pd

medications = pd.read_csv("D:/STUDY/Data_Science_Courses/PROJECTS/15.Cien HealthFlow Analytics/Cien-Healthflow-Analytics/Data/medications_reference.csv")
facility = pd.read_csv("D:/STUDY/Data_Science_Courses/PROJECTS/15.Cien HealthFlow Analytics/Cien-Healthflow-Analytics/Data/facility_monthly_metrics.csv")

for name, df in [
    ("Medications Reference", medications),
    ("Facility Monthly Metrics", facility)
]:
    print(f"\n===== {name} =====")
    print("Shape:", df.shape)
    print("\nColumns and data types:")
    print(df.dtypes)
    print("\nMissing values:")
    print(df.isnull().sum())
    print("\nDuplicate rows:", df.duplicated().sum())
    print("\nSample records:")
    print(df.head())