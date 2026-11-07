import { useEffect } from "react";
import { usePersisted } from "../../hooks";
import { SelectField } from "../../components/ui";

/** One course choice shared by every instructor page (falls back to the first course the token allows). */
export function useInstructorCourse(courses: { id: string; title: string }[]): [string, (id: string) => void] {
  const [course, setCourse] = usePersisted("instructor-course", "c-py-201");
  const valid = courses.some((c) => c.id === course);
  useEffect(() => { if (!valid && courses.length) setCourse(courses[0].id); }, [valid, courses, setCourse]);
  return [valid ? course : courses[0]?.id ?? "", setCourse];
}

export function CourseSelect({ courses, value, onChange }: { courses: { id: string; title: string }[]; value: string; onChange: (id: string) => void }) {
  return <SelectField label="Course" value={value} options={courses} onChange={onChange} render={(c) => c.title} valueOf={(c) => c.id} />;
}
