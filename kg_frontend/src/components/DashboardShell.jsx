// Dashboard shell: sidebar + main, exactly as the prototype's #dash .shell.
import Sidebar from './Sidebar';

export default function DashboardShell({ children }) {
  return (
    <div className="screen fade" id="dash">
      <div className="shell">
        <Sidebar />
        <main className="main">{children}</main>
      </div>
    </div>
  );
}
