from django.shortcuts import render, redirect
from dynamic.models import *
from dashboard.models import *
from .models import *
from django.contrib.auth.decorators import login_required

# Create your views here.
@login_required
def reports(request):
    formats = ReportFormat.objects.all()
    context = {
        'formats':formats,
        'gadgets':Gadgets.objects.all()
    }
    return render(request, 'reports.html', context)


@login_required
def addFormat(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        file_type = request.POST.get('file_type')
        template_file = request.FILES.get('template_file')
        description = request.POST.get('description')

        ReportFormat.objects.create(
            name=name,
            file_type=file_type,
            template_file=template_file,
            description=description
        )
        return redirect('/reports')  # adjust this to your reports list

    return redirect('/reports')  # fallback