import { DocFile, DocLink, DocTreeDir, SearchHit } from './docs-view-api';

/** Test data for the docs view. The names are made up: the UI knows no real project. */

export const PROJECTS = [
  { slug: 'my-game', name: 'My Game', doc_count: 3 },
  { slug: 'my-tools', name: 'My Tools', doc_count: 1 },
];

export const TREE: DocTreeDir = {
  type: 'dir',
  name: 'My Game',
  path: '',
  children: [
    {
      type: 'dir',
      name: 'docs',
      path: 'docs',
      children: [
        {
          type: 'dir',
          name: 'design',
          path: 'docs/design',
          children: [
            {
              type: 'file',
              name: 'vision.md',
              path: 'docs/design/vision.md',
              title: 'Vision',
              size: 900,
              modified: '2026-11-10T10:00:00Z',
              headings: [{ level: 1, text: 'Vision', line: 1 }],
            },
          ],
        },
        {
          type: 'file',
          name: 'README.md',
          path: 'docs/README.md',
          title: 'Docs home',
          size: 400,
          modified: '2026-11-11T02:09:13Z',
          headings: [{ level: 1, text: 'Docs home', line: 1 }],
        },
      ],
    },
    {
      type: 'file',
      name: 'CONTRIBUTING.md',
      path: 'CONTRIBUTING.md',
      title: 'Contributing',
      size: 100,
      modified: '2026-11-09T10:00:00Z',
      headings: [],
    },
  ],
};

export function link(
  overrides: Partial<DocLink> & { target: string; kind: DocLink['kind'] },
): DocLink {
  return { at: 1, image: false, ...overrides };
}

export function doc(
  text: string,
  links: DocLink[] = [],
  overrides: Partial<DocFile> = {},
): DocFile {
  return {
    path: 'docs/README.md',
    title: 'Docs home',
    text,
    headings: [],
    links,
    project: 'my-game',
    size: text.length,
    modified: '2026-11-11T02:09:13Z',
    ...overrides,
  };
}

export function hit(overrides: Partial<SearchHit> = {}): SearchHit {
  return {
    project: 'my-game',
    path: 'docs/design/vision.md',
    title: 'Vision',
    heading: 'Power use',
    line: 12,
    excerpt: 'Only one GPU lock is held at a time.',
    ...overrides,
  };
}
