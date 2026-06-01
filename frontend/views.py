from django.shortcuts import render


def dashboard(request):
    return render(request, 'frontend/dashboard.html')


def board(request):
    return render(request, 'frontend/board.html')


def score_idea(request):
    return render(request, 'frontend/score.html')


def idea_detail(request, idea_id):
    return render(request, 'frontend/idea_detail.html', {'idea_id': idea_id})


def research(request):
    return render(request, 'frontend/research.html')


def ba_explorer(request):
    return render(request, 'frontend/ba_explorer.html')
