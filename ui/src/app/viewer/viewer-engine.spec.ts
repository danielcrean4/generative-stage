import { BoxGeometry, Group, Mesh, MeshStandardMaterial } from 'three';
import { measure } from './viewer-engine';

describe('measure', () => {
  it('counts triangles, vertices, materials and size without a renderer', () => {
    const red = new MeshStandardMaterial({ name: 'red' });
    const blue = new MeshStandardMaterial({ name: 'blue' });
    const root = new Group();
    root.add(new Mesh(new BoxGeometry(1, 2, 3), red));
    root.add(new Mesh(new BoxGeometry(1, 1, 1), red));
    root.add(new Mesh(new BoxGeometry(1, 1, 1), blue));
    const info = measure(root);
    expect(info.triangles).toBe(36);
    expect(info.vertices).toBe(72);
    expect(info.materials.sort()).toEqual(['blue', 'red']);
    expect(info.size[0]).toBeCloseTo(1);
    expect(info.size[1]).toBeCloseTo(2);
    expect(info.size[2]).toBeCloseTo(3);
  });
});
