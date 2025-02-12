from django.urls import path
from .views import OptimalRouteView

urlpatterns = [
    path('optimal-route/', OptimalRouteView.as_view(), name='optimal-route'),
]
