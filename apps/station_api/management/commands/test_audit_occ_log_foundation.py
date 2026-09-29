from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.test import Client, RequestFactory
from django.urls import reverse

from apps.accounts.permissions import can_view_advanced_settings, can_view_security_audit
from apps.station_api.models import SecurityAuditLog
from apps.station_api.security_audit import record_security_audit


class Command(BaseCommand):
    help = "Self-test V6.5 audit RBAC and OCC audit feed foundation."

    def handle(self, *args, **options):
        User = get_user_model(); rf = RequestFactory()
        suffix = "__v65_audit_test__"
        users=[]
        try:
            for role in ("Operator","Maintainer","Administrator"):
                g,_=Group.objects.get_or_create(name=role)
                u=User.objects.create_user(username=f"{suffix}{role}",password="Tmp!234567")
                u.groups.add(g); users.append(u)
            op,maint,admin=users
            assert not can_view_advanced_settings(op)
            assert can_view_advanced_settings(maint) and not can_view_security_audit(maint)
            assert can_view_advanced_settings(admin) and can_view_security_audit(admin)
            self.stdout.write("PASS: human RBAC matrix")

            req=rf.get("/", REMOTE_ADDR="127.0.0.1", HTTP_USER_AGENT="self-test")
            req.user=admin
            row=record_security_audit(action="SELF_TEST", result="info", request=req, user=admin, metadata={"token":"must-not-persist","safe":"ok"})
            row.refresh_from_db()
            assert "token" not in row.metadata and row.metadata.get("safe")=="ok"
            self.stdout.write("PASS: append-only audit writer strips secret metadata")

            client=Client(HTTP_HOST="127.0.0.1"); client.force_login(maint)
            r=client.get(reverse("dashboard:system_log_list")+"?category=security")
            assert r.status_code==404
            self.stdout.write("PASS: Maintainer cannot open security audit UI")
            client.force_login(admin)
            r=client.get(reverse("dashboard:system_log_list")+"?category=security")
            assert r.status_code==200
            self.stdout.write("PASS: Administrator can open security audit UI")
            self.stdout.write(self.style.SUCCESS("V6.5 Audit & OCC Log API Foundation self-test PASSED."))
        except Exception as exc:
            raise CommandError(str(exc))
        finally:
            SecurityAuditLog.objects.filter(action="SELF_TEST", username__startswith=suffix).delete()
            User.objects.filter(username__startswith=suffix).delete()
