import { DocTreeDir, DocTreeFile, DocTreeNode } from './docs-view-api';

/** Small helpers over the docs tree the server sends. */

export function findDocFile(node: DocTreeNode, path: string): DocTreeFile | null {
  if (node.type === 'file') return node.path === path ? node : null;
  for (const child of node.children) {
    const hit = findDocFile(child, path);
    if (hit) return hit;
  }
  return null;
}

export function countDocFiles(node: DocTreeNode): number {
  return node.type === 'file' ? 1 : node.children.reduce((n, c) => n + countDocFiles(c), 0);
}

export function isDir(node: DocTreeNode): node is DocTreeDir {
  return node.type === 'dir';
}
