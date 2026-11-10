/** Route table with role-gated trees (Plan Phase 0 task 4; screens from Phases 1-7). */
import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, type RouteObject } from "react-router";
import { NAV } from "./nav";
import { RoleGate } from "./RoleGate";
import { landingFor, ROLE_HOME, ROLES, useSessionControls, type Role } from "./session";
import { StartPage } from "../routes/StartPage";
import { RolePlaceholder } from "../routes/RolePlaceholder";
import { NotFound } from "../routes/NotFound";
import { RedeemPage } from "../routes/auth/RedeemPage";
import { ResetPage } from "../routes/auth/ResetPage";
import { OnboardingPage } from "../routes/OnboardingPage";
import { VisibilityPage } from "../routes/account/VisibilityPage";
import { SettingsPage } from "../routes/account/SettingsPage";
import { TherapistsPage } from "../routes/admin/TherapistsPage";
import { JointPage } from "../features/joint/JointPage";
import { RoomPage } from "../features/joint/RoomPage";
import { JointBoardPage } from "../routes/therapist/JointBoardPage";
import { JointSummaryPage } from "../routes/therapist/JointSummaryPage";
import { SiteSettingsPage } from "../routes/admin/SiteSettingsPage";
import { AiStatusPage } from "../routes/admin/AiStatusPage";
import { KnowledgeBasePage } from "../routes/admin/KnowledgeBasePage";
import { ResearchExportPage } from "../routes/admin/ResearchExportPage";
import { FamilyPage } from "../routes/therapist/FamilyPage";
import { GroupPage, GroupsPage } from "../routes/therapist/GroupsPage";
import { HelpPage } from "../routes/safety/HelpPage";
import { SafetyEventPage } from "../routes/safety/SafetyEventPage";
import { SafetyQueuePage } from "../routes/safety/SafetyQueuePage";
import { HomePage } from "../features/lessons/HomePage";
import { LearnPage } from "../features/lessons/LearnPage";
import { LessonPage } from "../features/lessons/LessonPage";
import { TestPage } from "../features/lessons/TestPage";
import { ProfilePage } from "../features/lessons/ProfilePage";
import { GroupReviewPage } from "../features/lessons/GroupReviewPage";
import { ExplorePage } from "../features/lessons/ExplorePage";
import { CaregiverLessonPage } from "../features/lessons/CaregiverLessonPage";
import { DiaryPage } from "../features/diary/DiaryPage";
import { EntryPage } from "../features/diary/EntryPage";
import { DiaryReviewPage } from "../routes/therapist/DiaryReviewPage";
import { SchedulePage } from "../routes/therapist/SchedulePage";
import { ProgressPage } from "../routes/therapist/ProgressPage";
import { LearningReviewPage } from "../routes/therapist/LearningReviewPage";
import { ContentReviewPage } from "../routes/therapist/ContentReviewPage";
import { MetricsPage } from "../routes/therapist/MetricsPage";

// Development builds only (Plan §5.13.4): excluded from production bundles.
const Gallery = import.meta.env.DEV ? lazy(() => import("../routes/Gallery")) : null;

function Root() {
  const { user, loading } = useSessionControls();
  if (loading) return null;
  return user ? <Navigate to={landingFor(user)} replace /> : <StartPage />;
}

/** Screens built so far, keyed by `${role}:${nav path}`. Everything else is a placeholder. */
const SCREENS: Record<string, () => ReactNode> = {
  "adolescent:": () => <HomePage />,
  "caregiver:": () => <HomePage />,
  "adolescent:learn": () => <LearnPage />,
  "caregiver:learn": () => <ExplorePage />,
  "adolescent:group-review": () => <GroupReviewPage />,
  "caregiver:group-review": () => <GroupReviewPage />,
  "adolescent:profile": () => <ProfilePage />,
  "adolescent:diary": () => <DiaryPage />,
  "caregiver:diary": () => <DiaryPage />,
  "therapist:diary-review": () => <DiaryReviewPage />,
  "therapist:schedule": () => <SchedulePage />,
  "therapist:progress": () => <ProgressPage />,
  "therapist:content": () => <ContentReviewPage />,
  "therapist:metrics": () => <MetricsPage />,
  "therapist:joint": () => <JointBoardPage />,
  "adolescent:joint": () => <JointPage />,
  "caregiver:joint": () => <JointPage />,
  "adolescent:privacy": () => <VisibilityPage />,
  "caregiver:privacy": () => <VisibilityPage />,
  "adolescent:help": () => <HelpPage />,
  "caregiver:help": () => <HelpPage />,
  "therapist:": () => <GroupsPage />,
  "therapist:safety": () => <SafetyQueuePage />,
  "admin:": () => <TherapistsPage />,
  "admin:site": () => <SiteSettingsPage />,
  "admin:safety": () => <SafetyQueuePage />,
  "admin:knowledge": () => <KnowledgeBasePage />,
  "admin:ai": () => <AiStatusPage />,
  "admin:export": () => <ResearchExportPage />,
};

const EXTRA: Partial<Record<Role, RouteObject[]>> = {
  adolescent: [
    { path: "diary/new", element: <EntryPage /> },
    { path: "diary/:entryId", element: <EntryPage /> },
    { path: "learn/tests/:testId", element: <TestPage /> },
    { path: "learn/:sessionId", element: <LessonPage /> },
    { path: "joint/:sessionId", element: <RoomPage /> },
  ],
  caregiver: [
    { path: "learn/lesson/:lessonId", element: <CaregiverLessonPage /> },
    { path: "diary/new", element: <EntryPage /> },
    { path: "diary/:entryId", element: <EntryPage /> },
    { path: "joint/:sessionId", element: <RoomPage /> },
  ],
  therapist: [
    { path: "groups/:groupId", element: <GroupPage /> },
    { path: "families/:familyId", element: <FamilyPage /> },
    { path: "families/:familyId/diary", element: <DiaryReviewPage /> },
    { path: "families/:familyId/learning", element: <LearningReviewPage /> },
    { path: "safety/:eventId", element: <SafetyEventPage /> },
    { path: "joint/:sessionId", element: <JointSummaryPage /> },
  ],
  admin: [{ path: "safety/:eventId", element: <SafetyEventPage /> }],
};

export function buildRoutes(): RouteObject[] {
  const gate = (role: Role, el: ReactNode) => <RoleGate role={role}>{el}</RoleGate>;
  const roleTrees: RouteObject[] = ROLES.map((role) => ({
    path: ROLE_HOME[role],
    children: [
      ...NAV[role].map((item) => {
        const screen = SCREENS[`${role}:${item.path}`];
        return {
          ...(item.path ? { path: item.path } : { index: true }),
          element: gate(role, screen ? screen() : <RolePlaceholder titleKey={`nav.${item.key}`} />),
        };
      }),
      { path: "settings", element: gate(role, <SettingsPage />) },
      ...(EXTRA[role] ?? []).map((r) => ({
        ...r,
        element: gate(role, r.element),
      })),
    ],
  }));

  return [
    { path: "/", element: <Root /> },
    { path: "/redeem", element: <RedeemPage /> },
    { path: "/reset", element: <ResetPage /> },
    { path: "/onboarding", element: <OnboardingPage /> },
    ...roleTrees,
    ...(Gallery
      ? [
          {
            path: "/dev/gallery",
            element: (
              <Suspense fallback={null}>
                <Gallery />
              </Suspense>
            ),
          },
        ]
      : []),
    { path: "*", element: <NotFound /> },
  ];
}
