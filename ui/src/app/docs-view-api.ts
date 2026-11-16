import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { RUN_VIEW_BASE } from './run-view-api';

/** Response shapes of the docs routes of the read-only server (server/docs/docs_view.md). */

export interface DocsProject {
  slug: string;
  name: string;
  doc_count: number;
}

export interface ProjectsResponse {
  projects: DocsProject[];
}

export interface DocHeading {
  level: number;
  text: string;
  line: number;
}

export interface DocTreeFile {
  type: 'file';
  name: string;
  path: string;
  title: string;
  size: number;
  modified: string;
  headings: DocHeading[];
}

export interface DocTreeDir {
  type: 'dir';
  name: string;
  path: string;
  children: DocTreeNode[];
}

export type DocTreeNode = DocTreeDir | DocTreeFile;

export interface DocsTreeResponse {
  project: string;
  count: number;
  tree: DocTreeDir;
}

/** The kinds of link the server sorts every markdown link into. */
export type DocLinkKind = 'doc' | 'source' | 'external' | 'anchor' | 'outside' | 'unsupported';

export interface DocLink {
  /** The link exactly as written in the markdown. */
  target: string;
  /** Line of the link in the doc. */
  at: number;
  image: boolean;
  kind: DocLinkKind;
  /** doc and source links: path relative to the repo. */
  path?: string;
  /** doc links: the `#anchor` as written, without the hash. */
  anchor?: string | null;
  /** doc and source links. */
  exists?: boolean;
  /** source links: true only when the file is inside the project's source allowlist. */
  allowed?: boolean;
  /** source links: the `:line` part, if any. */
  line?: number | null;
  /** external links. */
  url?: string;
}

export interface DocFile {
  path: string;
  title: string;
  text: string;
  headings: DocHeading[];
  links: DocLink[];
  /** Sent by the server but not in the documented example; the tree also has it. */
  project?: string;
  size?: number;
  modified?: string;
}

export interface SourceWindow {
  path: string;
  total_lines: number;
  /** First and last line of the window, 1-based. */
  start: number;
  end: number;
  truncated: boolean;
  lines: string[];
}

export interface SearchHit {
  project: string;
  path: string;
  title: string;
  /** The nearest heading above the hit; may be empty above the first heading. */
  heading: string;
  line: number;
  excerpt: string;
}

export interface SearchResponse {
  docs_matched: number;
  total_hits: number;
  truncated: boolean;
  hits: SearchHit[];
}

export const DOC_SEARCH_LIMIT = 50;
export const SOURCE_WINDOW_LINES = 200;

/** Every call to the docs routes of the read-only server (port 8781, proxied at /api/ro). */
@Injectable({ providedIn: 'root' })
export class DocsViewApi {
  private readonly http = inject(HttpClient);

  projects(): Observable<ProjectsResponse> {
    return this.http.get<ProjectsResponse>(`${RUN_VIEW_BASE}/projects`);
  }

  tree(project: string): Observable<DocsTreeResponse> {
    return this.http.get<DocsTreeResponse>(`${this.projectUrl(project)}/docs`);
  }

  file(project: string, path: string): Observable<DocFile> {
    return this.http.get<DocFile>(`${this.projectUrl(project)}/docs/file`, { params: { path } });
  }

  source(
    project: string,
    path: string,
    line?: number | null,
    window = SOURCE_WINDOW_LINES,
  ): Observable<SourceWindow> {
    let params = new HttpParams().set('path', path).set('window', window);
    if (line) params = params.set('line', line);
    return this.http.get<SourceWindow>(`${this.projectUrl(project)}/source`, { params });
  }

  /** Search one project. */
  search(project: string, q: string, limit = DOC_SEARCH_LIMIT): Observable<SearchResponse> {
    return this.http.get<SearchResponse>(`${this.projectUrl(project)}/docs/search`, {
      params: { q, limit },
    });
  }

  /** Search every registered project. */
  searchAll(q: string, limit = DOC_SEARCH_LIMIT): Observable<SearchResponse> {
    return this.http.get<SearchResponse>(`${RUN_VIEW_BASE}/docs/search`, { params: { q, limit } });
  }

  private projectUrl(project: string): string {
    return `${RUN_VIEW_BASE}/projects/${encodeURIComponent(project)}`;
  }
}
