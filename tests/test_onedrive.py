import os

from core.onedrive import is_onedrive_synced_path


_MOUNTS = [
    r"C:\Users\ritesh\OneDrive - Madison Logic Inc",
    r"C:\Users\ritesh\Madison Logic Inc\CRS Team - Documents",
]


def test_blank_path_is_never_onedrive_synced():
    assert is_onedrive_synced_path("", mount_points=_MOUNTS) is False


def test_path_directly_under_personal_onedrive_mount_is_synced():
    path = r"C:\Users\ritesh\OneDrive - Madison Logic Inc\Lead QA Clients"
    assert is_onedrive_synced_path(path, mount_points=_MOUNTS) is True


def test_path_under_a_synced_sharepoint_team_library_is_synced():
    # This is Dell APAC's own real setup: a SharePoint team-site library
    # synced via "Sync", which lands OUTSIDE the plain %OneDrive% folder --
    # a naive "must be under %OneDrive%" check would wrongly reject this.
    path = r"C:\Users\ritesh\Madison Logic Inc\CRS Team - Documents\Lead QA Automation Clients"
    assert is_onedrive_synced_path(path, mount_points=_MOUNTS) is True


def test_path_on_a_completely_different_local_folder_is_not_synced():
    path = r"C:\Users\ritesh\Downloads\MyLeads"
    assert is_onedrive_synced_path(path, mount_points=_MOUNTS) is False


def test_path_on_a_different_drive_letter_is_not_synced():
    path = r"D:\Shared\LeadQA"
    assert is_onedrive_synced_path(path, mount_points=_MOUNTS) is False


def test_a_folder_that_merely_starts_with_the_same_prefix_is_not_synced():
    # "OneDrive - Madison Logic IncExtra" is not actually inside the mount
    # point -- a plain string .startswith() check would wrongly accept it.
    path = r"C:\Users\ritesh\OneDrive - Madison Logic IncExtra\Clients"
    assert is_onedrive_synced_path(path, mount_points=_MOUNTS) is False


def test_the_mount_point_itself_counts_as_synced():
    assert is_onedrive_synced_path(_MOUNTS[0], mount_points=_MOUNTS) is True


def test_real_machine_detection_finds_this_machines_actual_onedrive_mount(monkeypatch):
    # Sanity check against the real detection path (env vars + registry) on
    # whatever machine actually runs this test suite.
    monkeypatch.setenv("OneDrive", r"C:\Users\someone\OneDrive - Example Co")
    assert is_onedrive_synced_path(r"C:\Users\someone\OneDrive - Example Co\Docs") is True
    assert is_onedrive_synced_path(r"C:\Users\someone\Downloads") is False
