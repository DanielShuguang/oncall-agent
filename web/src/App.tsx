import { Link, Navigate, Route, Routes } from 'react-router-dom';
import ChatPage from './features/chat/ChatPage';
import ConsolePage from './features/console/ConsolePage';

export default function App() {
  return (
    <div className="oncall-shell">
      <header className="oncall-header">
        <h1>OnCall</h1>
        <span className="oncall-badge">私有化企业智能体</span>
        <nav style={{ marginLeft: 'auto', display: 'flex', gap: 12, fontSize: 13 }}>
          <Link to="/">对话</Link>
          <Link to="/console/kb">管理后台</Link>
        </nav>
      </header>

      <Routes>
        <Route path="/" element={<ChatPage />} />
        <Route path="/console/*" element={<ConsolePage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
}
