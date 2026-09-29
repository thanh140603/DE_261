import { NavLink } from "react-router-dom";

const items = [
  { to: "/learner", who: "Learner", brs: "notifications, next step, code feedback" },
  { to: "/instructor", who: "Instructor", brs: "assessments, heatmap, engagement, content" },
  { to: "/advisor", who: "Advisor", brs: "drop-out risk" },
  { to: "/admin", who: "Admin", brs: "organisation progress" },
  { to: "/pipeline", who: "Pipeline", brs: "simulator, topics, silver, dead letters" },
];

export function Rail() {
  return (
    <aside className="rail">
      <nav aria-label="Stakeholder views">
        {items.map((i) => (
          <NavLink key={i.to} to={i.to} className={({ isActive }) => (isActive ? "active" : undefined)}>
            <span className="who">{i.who}</span>
            <span className="brs">{i.brs}</span>
          </NavLink>
        ))}
      </nav>
      <p className="note">Every view names the business requirement it demonstrates. Controls sit next to the outcome they change.</p>
    </aside>
  );
}
