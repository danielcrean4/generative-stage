import { Routes } from '@angular/router';
import { AttemptView } from './components/attempt-view/attempt-view';
import { RunDetail } from './components/run-detail/run-detail';
import { RunsList } from './components/runs-list/runs-list';
import { SWITCHING_ROUTE } from './world/world-project.service';
import { unsavedChangesGuard } from './world/unsaved-changes.guard';

export const routes: Routes = [
  // "/" needs an explicit landing page or it is blank. The landing page is the list of world projects.
  { path: '', redirectTo: 'projects', pathMatch: 'full' },
  // The world model (v1 API): projects, then each kind's list, schema and entities. Loaded on demand.
  { path: 'projects', loadComponent: () => import('./world/projects-page').then((m) => m.ProjectsPage) },
  { path: 'world/:kind', loadComponent: () => import('./world/entity-list-page').then((m) => m.EntityListPage) },
  { path: 'world/:kind/batch', loadComponent: () => import('./world/parametric-batch-page').then((m) => m.ParametricBatchPage) },
  { path: 'world/:kind/batch/:batchId', loadComponent: () => import('./world/parametric-batch-page').then((m) => m.ParametricBatchPage) },
  { path: 'world/:kind/schema', loadComponent: () => import('./world/kind-page').then((m) => m.KindPage) },
  // An entity opens on its profile; the full form (new, bulk edits, archive, revisions, links) sits beside it.
  {
    path: 'world/:kind/new',
    loadComponent: () => import('./world/entity-page').then((m) => m.EntityPage),
    canDeactivate: [unsavedChangesGuard],
  },
  { path: 'world/:kind/:id', loadComponent: () => import('./world/profile-page').then((m) => m.ProfilePage) },
  { path: 'world/:kind/:id/runs/:runId', loadComponent: () => import('./world/trace-page').then((m) => m.TracePage) },
  { path: 'sources', loadComponent: () => import('./world/sources-page').then((m) => m.SourcesPage) },
  { path: 'sources/:type/:id', loadComponent: () => import('./world/source-page').then((m) => m.SourcePage) },
  { path: 'vocabulary', loadComponent: () => import('./world/vocabulary-page').then((m) => m.VocabularyPage) },
  { path: 'story', loadComponent: () => import('./world/story-page').then((m) => m.StoryPage) },
  { path: 'statistics', loadComponent: () => import('./world/statistics-page').then((m) => m.StatisticsPage) },
  {
    path: 'world/:kind/:id/edit',
    loadComponent: () => import('./world/entity-page').then((m) => m.EntityPage),
    canDeactivate: [unsavedChangesGuard],
  },
  // Blank page a project switch passes through (see ProjectService.switchTo).
  { path: SWITCHING_ROUTE, children: [] },
  { path: 'runs', component: RunsList },
  { path: 'runs/:runId', component: RunDetail },
  { path: 'runs/:runId/attempts/:attemptId', component: AttemptView },
  // The docs routes load on demand: they carry the markdown renderer, which no other page needs.
  { path: 'docs', loadComponent: () => import('./components/docs-home/docs-home').then((m) => m.DocsHome) },
  { path: 'docs/:project', loadComponent: () => import('./components/docs-home/docs-home').then((m) => m.DocsHome) },
  { path: 'docs/:project/file', loadComponent: () => import('./components/docs-file/docs-file').then((m) => m.DocsFile) },
  { path: 'docs/:project/source', loadComponent: () => import('./components/docs-source/docs-source').then((m) => m.DocsSource) },
];
