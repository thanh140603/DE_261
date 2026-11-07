import { Navigate, Route, Routes } from "react-router-dom";
import { Shell } from "./components/Shell";
import { LearnerHome } from "./views/learner/LearnerHome";
import { CodeLab } from "./views/learner/CodeLab";
import { AssessmentHealth } from "./views/instructor/AssessmentHealth";
import { VideoInsights } from "./views/instructor/VideoInsights";
import { EngagementTrend } from "./views/instructor/EngagementTrend";
import { ContentSearch } from "./views/instructor/ContentSearch";
import { AdvisorView } from "./views/AdvisorView";
import { AdminView } from "./views/AdminView";
import { PipelineView } from "./views/PipelineView";

export default function App() {
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Navigate to="/learner" replace />} />
        <Route path="/learner" element={<LearnerHome />} />
        <Route path="/learner/code-lab" element={<CodeLab />} />
        <Route path="/instructor" element={<Navigate to="/instructor/assessments" replace />} />
        <Route path="/instructor/assessments" element={<AssessmentHealth />} />
        <Route path="/instructor/videos" element={<VideoInsights />} />
        <Route path="/instructor/engagement" element={<EngagementTrend />} />
        <Route path="/instructor/content" element={<ContentSearch />} />
        <Route path="/advisor" element={<AdvisorView />} />
        <Route path="/admin" element={<AdminView />} />
        <Route path="/pipeline" element={<PipelineView />} />
        <Route path="*" element={<Navigate to="/learner" replace />} />
      </Routes>
    </Shell>
  );
}
