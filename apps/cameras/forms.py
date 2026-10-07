from django import forms

from .mediamtx import phase1_camera_codes
from .monitor_profiles import load_monitor_profile_config


class MonitorProfileForm(forms.Form):
    """驗證Monitor layout要求的媒體profile。"""

    profile = forms.CharField(max_length=32)

    def clean_profile(self):
        profile_name = self.cleaned_data["profile"].strip().lower()
        if profile_name not in load_monitor_profile_config()["profiles"]:
            raise forms.ValidationError("Unsupported monitor profile.")
        return profile_name


class MonitorTransitionAckForm(forms.Form):
    """驗證前端完成A/B WebRTC全組預載後送出的確認資料。"""

    transition_id = forms.CharField(max_length=64)
    camera_codes = forms.CharField(max_length=256)

    def clean_transition_id(self):
        transition_id = self.cleaned_data["transition_id"].strip()
        if not transition_id.isascii() or any(
            not (character.isalnum() or character == "-")
            for character in transition_id
        ):
            raise forms.ValidationError("Invalid transition identifier.")
        return transition_id

    def clean_camera_codes(self):
        camera_codes = [
            value.strip().upper()
            for value in self.cleaned_data["camera_codes"].split(",")
            if value.strip()
        ]
        if (
            not camera_codes
            or len(camera_codes) != len(set(camera_codes))
            or any(code not in phase1_camera_codes() for code in camera_codes)
        ):
            raise forms.ValidationError("Invalid Camera codes.")
        return camera_codes
