import { HttpInterceptorFn } from '@angular/common/http';

/**
 * The one place request headers for the server are set: every non-GET gets `X-Studio-Request`
 * (the server refuses a write without it). No component sets it itself.
 */
export const studioHeaderInterceptor: HttpInterceptorFn = (req, next) =>
  req.method === 'GET' ? next(req) : next(req.clone({ setHeaders: { 'X-Studio-Request': '1' } }));
