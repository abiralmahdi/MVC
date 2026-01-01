import pandas as pd
from pprint import pprint

df = pd.read_excel("ECO101.34-3.xlsx", sheet_name="NSU - SIS")
df = df.fillna(0)

def findBest2QuizSummation(quiz1, quiz2, quiz3):
    largest = 0
    large2 = 0
    if quiz1 >= quiz2 and quiz1 >= quiz3:
        largest = quiz1
        if quiz2 >= quiz3:
            large2 = quiz2
        else:
            large2 = quiz3
    elif quiz2 >= quiz1 and quiz2 >= quiz3:
        largest = quiz2
        if quiz1 >= quiz3:
            large2 = quiz1
        else:
            large2 = quiz3
    elif quiz3 >= quiz1 and quiz3 >= quiz2:
        largest = quiz3
        if quiz2 >= quiz1:
            large2 = quiz2
        else:
            large2 = quiz1
    
    return (large2 + largest)/2

studentID = []
totalMarks = []

for index, row in df.iterrows():
    id = row['Student ID']
    quiz1 = float(row['Quiz 1 (Out of 15)'])
    quiz2 = float(row['Quiz 2 (Out of 15)'])
    quiz3 = float(row['Quiz 3 (Out of 15)'])
    mid1 = float(row['Midterm 1 (out of 40) 25%'])*25/40
    mid2 = float(row['Midterm 2 (out of 40) 25%'])*25/40
    final = float(row['Final (Out of 30) 30%'])
    # final = 25
    bestQuiz = findBest2QuizSummation(quiz1, quiz2, quiz3)
    total = bestQuiz + mid1 + mid2 + final

    studentID.append(int(id))
    totalMarks.append(total)

# Zip, sort by list1 descending, unzip
combined = sorted(zip(totalMarks, studentID), reverse=True)

totalMarks_sorted, studentID_sorted = zip(*combined)
dictt = {}

for sid, mark in zip(studentID_sorted, totalMarks_sorted):
    dictt[sid] = mark

count = 1
for sid, mark in dictt.items():
    print(f"{count}. {sid}: {mark}")
    count += 1



