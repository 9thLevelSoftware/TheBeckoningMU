from django.contrib.auth.mixins import UserPassesTestMixin
from django.urls import path
from oauth2_provider.views.application import (
    ApplicationDelete,
    ApplicationDetail,
    ApplicationList,
    ApplicationRegistration,
    ApplicationUpdate,
)

app_name = "staff_oauth_apps"


class StaffOnlyApplicationView(UserPassesTestMixin):
    raise_exception = True

    def test_func(self):
        return self.request.user.is_staff


class StaffApplicationList(StaffOnlyApplicationView, ApplicationList):
    pass


class StaffApplicationRegistration(StaffOnlyApplicationView, ApplicationRegistration):
    pass


class StaffApplicationDetail(StaffOnlyApplicationView, ApplicationDetail):
    pass


class StaffApplicationDelete(StaffOnlyApplicationView, ApplicationDelete):
    pass


class StaffApplicationUpdate(StaffOnlyApplicationView, ApplicationUpdate):
    pass


urlpatterns = [
    path("", StaffApplicationList.as_view(), name="list"),
    path("register/", StaffApplicationRegistration.as_view(), name="register"),
    path("<slug:pk>/", StaffApplicationDetail.as_view(), name="detail"),
    path("<slug:pk>/delete/", StaffApplicationDelete.as_view(), name="delete"),
    path("<slug:pk>/update/", StaffApplicationUpdate.as_view(), name="update"),
]
