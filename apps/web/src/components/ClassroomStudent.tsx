import { useState } from "react";
import { Outlet } from "react-router-dom";
import { api } from "../api";
import { useAction, useFetch } from "../hooks";
import { useStore } from "../store";
import type { Course } from "../types";
import { Btn, Callout, Card, Status } from "./ui";

export function LearnerAccess() {
  const { overview, student, setStudent, studentLoading, studentError } = useStore();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const login = useAction(async () => {
    setStudent(await api.classroom.login(username.trim(), password));
    setPassword("");
  });
  if (!overview) return null;
  if (!overview.classroom || student) return <Outlet />;
  if (studentLoading) return <p role="status">Checking classroom session…</p>;

  return <section className="card signin" aria-label="Classroom learner sign-in">
    <h2>Learner sign-in</h2>
    {(studentError || login.error) && <Callout tone="bad">{login.error ?? studentError}</Callout>}
    <form onSubmit={(e) => { e.preventDefault(); void login.run(); }}>
      <label className="field">Username
        <input className="input full" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
      </label>
      <label className="field">Password
        <input className="input full" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
      </label>
      <Btn type="submit" variant="primary" disabled={login.pending}>Sign in</Btn>
    </form>
  </section>;
}

export function ClassroomLessons({ courses }: { courses: Course[] }) {
  const { student } = useStore();
  const lessons = useFetch(() => api.classroom.lessons(), [student?.id]);
  const study = useAction(async (lesson: string, kind: "lesson_view" | "lesson_complete") => {
    await api.classroom.study(lesson, kind);
    await lessons.reload();
  });
  if (!courses.some((course) => course.lessons.length)) return null;

  return <Card title="Classroom lessons">
    <Status loading={lessons.loading && !lessons.data} error={lessons.error}>
      {study.error && <Callout tone="bad">{study.error}</Callout>}
      {courses.map((course) => <section key={course.id} className="mt">
        <h3>{course.title}</h3>
        <ul className="reason-list">
          {course.lessons.map((lesson) => {
            const progress = lessons.data?.find((row) => row.lesson_id === lesson.id);
            return <li key={lesson.id}>
              <span>{lesson.title}</span>
              {progress?.completed_at ? <span>Completed</span> : <Btn disabled={study.pending}
                onClick={() => void study.run(lesson.id, progress ? "lesson_complete" : "lesson_view")}>
                {progress ? "Complete lesson" : "Start lesson"}
              </Btn>}
            </li>;
          })}
        </ul>
      </section>)}
    </Status>
  </Card>;
}
