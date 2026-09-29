import { Navigate, Route, Routes } from "react-router-dom";
import { TopBar } from "./components/TopBar";
import { FlowStrip } from "./components/FlowStrip";
import { Rail } from "./components/Rail";
import { EventDrawer } from "./components/EventDrawer";
import { LearnerView } from "./views/LearnerView";
import { InstructorView } from "./views/InstructorView";
import { AdvisorView } from "./views/AdvisorView";
import { AdminView } from "./views/AdminView";
import { PipelineView } from "./views/PipelineView";
import { useStore } from "./store";

export default function App() {
  const { overviewError } = useStore();
  return (
    <div className="shell">
      <TopBar />
      <FlowStrip />
      <div className="body">
        <Rail />
        <main className="main">
          {overviewError && (
            <div className="error">
              The server is not reachable ({overviewError}). Start it with <code>uvicorn edu_platform.entrypoints.api.main:app</code> and reload.
            </div>
          )}
          <Routes>
            <Route path="/" element={<Navigate to="/learner" replace />} />
            <Route path="/learner" element={<LearnerView />} />
            <Route path="/instructor" element={<InstructorView />} />
            <Route path="/advisor" element={<AdvisorView />} />
            <Route path="/admin" element={<AdminView />} />
            <Route path="/pipeline" element={<PipelineView />} />
            <Route path="*" element={<Navigate to="/learner" replace />} />
          </Routes>
        </main>
      </div>
      <EventDrawer />
    </div>
  );
}
