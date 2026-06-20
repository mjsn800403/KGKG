// app/settings/page.js — account settings view (exact prototype)
import DashboardShell from '@/components/DashboardShell';
import Switch from '@/components/Switch';

export default function Settings() {
  return (
    <DashboardShell>
      <div className="topbar"><div className="breadcrumb"><b>تنظیمات حساب</b></div></div>
      <h1 className="page-title">تنظیمات حساب کاربری</h1>
      <div className="page-sub">// ACCOUNT_SETTINGS</div>
      <div className="settings-grid">
        <div className="settings-tabs">
          <div className="stab active">اطلاعات حساب</div>
          <div className="stab">اعلان‌ها</div>
          <div className="stab">امنیت و دسترسی</div>
        </div>
        <div>
          <div className="notif-item glass">
            <div><div className="t">اعلان خرید مستند جدید</div><div className="d">با هر خرید موفق مستند، اعلان دریافت کنید</div></div>
            <Switch on />
          </div>
          <div className="notif-item glass">
            <div><div className="t">اعلان به‌روزرسانی منوال تعمیر</div><div className="d">هنگام به‌روزرسانی محتوای مستندات خریداری‌شده</div></div>
            <Switch on />
          </div>
          <div className="notif-item glass">
            <div><div className="t">اعلان ورود از دستگاه جدید</div><div className="d">هشدار امنیتی برای ورود از دستگاه ناشناس</div></div>
            <Switch on />
          </div>
          <div className="notif-item glass">
            <div><div className="t">خلاصه هفتگی فعالیت</div><div className="d">ایمیل خلاصه فعالیت‌های حساب هر هفته</div></div>
            <Switch />
          </div>
        </div>
      </div>
    </DashboardShell>
  );
}
