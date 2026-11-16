import { TestBed } from '@angular/core/testing';
import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { studioHeaderInterceptor } from './studio-header.interceptor';

describe('studioHeaderInterceptor', () => {
  let client: HttpClient;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(withInterceptors([studioHeaderInterceptor])), provideHttpClientTesting()],
    });
    client = TestBed.inject(HttpClient);
    http = TestBed.inject(HttpTestingController);
  });
  afterEach(() => http.verify());

  it('leaves reads alone', () => {
    client.get('/api/v1/projects').subscribe();
    const req = http.expectOne('/api/v1/projects');
    expect(req.request.headers.has('X-Studio-Request')).toBe(false);
    expect(req.request.headers.has('X-Studio-Project')).toBe(false);
    req.flush([]);
  });

  it('marks every write, whichever server it goes to', () => {
    for (const url of ['/api/v1/projects/sample/entities', '/api/ro/x']) {
      client.post(url, {}).subscribe();
      const req = http.expectOne(url);
      expect(req.request.headers.get('X-Studio-Request')).toBe('1');
      req.flush({});
    }
  });
});
