'use client';

// app/team/chats/page.jsx — assistant conversations of the users in the
// viewer's org-graph reach (same gate and scope as team analytics).
import DashboardShell from '@/components/DashboardShell';
import UserChip from '@/components/UserChip';
import ChatLogsView from '@/components/ChatLogsView';
import { teamApi } from '@/utils/api';

export default function TeamChatsPage() {
  return (
    <DashboardShell>
      <div className="topbar">
        <div className="breadcrumb"><b>گفتگوهای دستیار</b></div>
        <UserChip />
      </div>
      <h1 className="page-title">گفتگوهای کارکنان با دستیار</h1>
      <div className="page-sub">پرسش‌ها و پاسخ‌های دستیار هوشمند برای کارکنان زیرمجموعهٔ شما</div>
      <ChatLogsView fetcher={teamApi.chatLogs} />
    </DashboardShell>
  );
}
