// app/settings/page.tsx — account settings (interactive tabs + theme picker)
import DashboardShell from '@/components/DashboardShell';
import SettingsView from '@/components/SettingsView';

export default function Settings() {
  return (
    <DashboardShell>
      <div className="topbar"><div className="breadcrumb"><b>تنظیمات حساب</b></div></div>
      <h1 className="page-title">تنظیمات حساب کاربری</h1>
      <div className="page-sub">// ACCOUNT_SETTINGS</div>
      <SettingsView />
    </DashboardShell>
  );
}
