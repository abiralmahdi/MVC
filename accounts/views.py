from django.shortcuts import render

# Create your views here.
def login_(reqeust):
    return render(reqeust, 'login.html')

def loginHistory(request):
    return render(request, 'loginHistory.html')

