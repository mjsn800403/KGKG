# ZAP Scanning Report

ZAP by [Checkmarx](https://checkmarx.com/).


## Summary of Alerts

| Risk Level | Number of Alerts |
| --- | --- |
| High | 0 |
| Medium | 2 |
| Low | 2 |
| Informational | 6 |




## Insights

| Level | Reason | Site | Description | Statistic |
| --- | --- | --- | --- | --- |
| Medium | Exceeded High | http://127.0.0.1:8130 | Percentage of responses with status code 4xx | 78 % |
| Info | Informational | http://127.0.0.1:8130 | Percentage of responses with status code 2xx | 20 % |
| Info | Informational | http://127.0.0.1:8130 | Percentage of endpoints with content type application/json | 92 % |
| Info | Informational | http://127.0.0.1:8130 | Percentage of endpoints with content type text/event-stream | 1 % |
| Info | Informational | http://127.0.0.1:8130 | Percentage of endpoints with content type text/html | 6 % |
| Info | Informational | http://127.0.0.1:8130 | Percentage of endpoints with method DELETE | 1 % |
| Info | Informational | http://127.0.0.1:8130 | Percentage of endpoints with method GET | 89 % |
| Info | Informational | http://127.0.0.1:8130 | Percentage of endpoints with method PATCH | 1 % |
| Info | Informational | http://127.0.0.1:8130 | Percentage of endpoints with method POST | 9 % |
| Info | Informational | http://127.0.0.1:8130 | Count of total endpoints | 423    |
| Info | Informational | http://127.0.0.1:8130 | Percentage of slow responses | 3 % |







## Alerts

| Name | Risk Level | Number of Instances |
| --- | --- | --- |
| CSP: script-src unsafe-inline | Medium | 5 |
| CSP: style-src unsafe-inline | Medium | 5 |
| Cross-Origin-Embedder-Policy Header Missing or Invalid | Low | 1 |
| Unexpected Content-Type was returned | Low | 33 |
| A Client Error response code was returned by the server | Informational | 411 |
| Authentication Request Identified | Informational | 2 |
| Information Disclosure - Sensitive Information in URL | Informational | 4 |
| Non-Storable Content | Informational | Systemic |
| Storable and Cacheable Content | Informational | 2 |
| Storable but Non-Cacheable Content | Informational | 1 |




## Alert Detail



### [ CSP: script-src unsafe-inline ](https://www.zaproxy.org/docs/alerts/10055/)



##### Medium (High)

### Description

Content Security Policy (CSP) is an added layer of security that helps to detect and mitigate certain types of attacks. Including (but not limited to) Cross Site Scripting (XSS), and data injection attacks. These attacks are used for everything from data theft to site defacement or distribution of malware. CSP provides a set of standard HTTP headers that allow website owners to declare approved sources of content that browsers should be allowed to load on that page — covered types are JavaScript, CSS, HTML frames, fonts, images and embeddable objects such as Java applets, ActiveX, audio and video files.

* URL: http://127.0.0.1:8130/kg-api/api/grafana-auth/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/grafana-auth/`
  * Method: `GET`
  * Parameter: `Content-Security-Policy`
  * Attack: ``
  * Evidence: `default-src 'self'; script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com https://static.cloudflareinsights.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data: blob:; font-src 'self' data: https://fonts.gstatic.com; connect-src 'self' https://cloudflareinsights.com https://challenges.cloudflare.com; frame-src 'self' https://challenges.cloudflare.com; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'`
  * Other Info: `script-src includes unsafe-inline.`
* URL: http://127.0.0.1:8130/kg-api/api/media-auth/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/media-auth/`
  * Method: `GET`
  * Parameter: `Content-Security-Policy`
  * Attack: ``
  * Evidence: `default-src 'self'; script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com https://static.cloudflareinsights.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data: blob:; font-src 'self' data: https://fonts.gstatic.com; connect-src 'self' https://cloudflareinsights.com https://challenges.cloudflare.com; frame-src 'self' https://challenges.cloudflare.com; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'`
  * Other Info: `script-src includes unsafe-inline.`
* URL: http://127.0.0.1:8130/kg-api/api/metrics/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/metrics/`
  * Method: `GET`
  * Parameter: `Content-Security-Policy`
  * Attack: ``
  * Evidence: `default-src 'self'; script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com https://static.cloudflareinsights.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data: blob:; font-src 'self' data: https://fonts.gstatic.com; connect-src 'self' https://cloudflareinsights.com https://challenges.cloudflare.com; frame-src 'self' https://challenges.cloudflare.com; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'`
  * Other Info: `script-src includes unsafe-inline.`
* URL: http://127.0.0.1:8130/kg-api/api/vnc-auth/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/vnc-auth/`
  * Method: `GET`
  * Parameter: `Content-Security-Policy`
  * Attack: ``
  * Evidence: `default-src 'self'; script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com https://static.cloudflareinsights.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data: blob:; font-src 'self' data: https://fonts.gstatic.com; connect-src 'self' https://cloudflareinsights.com https://challenges.cloudflare.com; frame-src 'self' https://challenges.cloudflare.com; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'`
  * Other Info: `script-src includes unsafe-inline.`
* URL: http://127.0.0.1:8130/kg-api/api/invite/x/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/invite/x/ ()({password})`
  * Method: `POST`
  * Parameter: `Content-Security-Policy`
  * Attack: ``
  * Evidence: `default-src 'self'; script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com https://static.cloudflareinsights.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data: blob:; font-src 'self' data: https://fonts.gstatic.com; connect-src 'self' https://cloudflareinsights.com https://challenges.cloudflare.com; frame-src 'self' https://challenges.cloudflare.com; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'`
  * Other Info: `script-src includes unsafe-inline.`


Instances: 5

### Solution

Ensure that your web server, application server, load balancer, etc. is properly configured to set the Content-Security-Policy header.

### Reference


* [ https://www.w3.org/TR/CSP/ ](https://www.w3.org/TR/CSP/)
* [ https://caniuse.com/#search=content+security+policy ](https://caniuse.com/#search=content+security+policy)
* [ https://content-security-policy.com/ ](https://content-security-policy.com/)
* [ https://github.com/HtmlUnit/htmlunit-csp ](https://github.com/HtmlUnit/htmlunit-csp)
* [ https://web.dev/articles/csp#resource-options ](https://web.dev/articles/csp#resource-options)


#### CWE Id: [ 693 ](https://cwe.mitre.org/data/definitions/693.html)


#### WASC Id: 15

#### Source ID: 3

### [ CSP: style-src unsafe-inline ](https://www.zaproxy.org/docs/alerts/10055/)



##### Medium (High)

### Description

Content Security Policy (CSP) is an added layer of security that helps to detect and mitigate certain types of attacks. Including (but not limited to) Cross Site Scripting (XSS), and data injection attacks. These attacks are used for everything from data theft to site defacement or distribution of malware. CSP provides a set of standard HTTP headers that allow website owners to declare approved sources of content that browsers should be allowed to load on that page — covered types are JavaScript, CSS, HTML frames, fonts, images and embeddable objects such as Java applets, ActiveX, audio and video files.

* URL: http://127.0.0.1:8130/kg-api/api/grafana-auth/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/grafana-auth/`
  * Method: `GET`
  * Parameter: `Content-Security-Policy`
  * Attack: ``
  * Evidence: `default-src 'self'; script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com https://static.cloudflareinsights.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data: blob:; font-src 'self' data: https://fonts.gstatic.com; connect-src 'self' https://cloudflareinsights.com https://challenges.cloudflare.com; frame-src 'self' https://challenges.cloudflare.com; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'`
  * Other Info: `style-src includes unsafe-inline.`
* URL: http://127.0.0.1:8130/kg-api/api/media-auth/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/media-auth/`
  * Method: `GET`
  * Parameter: `Content-Security-Policy`
  * Attack: ``
  * Evidence: `default-src 'self'; script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com https://static.cloudflareinsights.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data: blob:; font-src 'self' data: https://fonts.gstatic.com; connect-src 'self' https://cloudflareinsights.com https://challenges.cloudflare.com; frame-src 'self' https://challenges.cloudflare.com; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'`
  * Other Info: `style-src includes unsafe-inline.`
* URL: http://127.0.0.1:8130/kg-api/api/metrics/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/metrics/`
  * Method: `GET`
  * Parameter: `Content-Security-Policy`
  * Attack: ``
  * Evidence: `default-src 'self'; script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com https://static.cloudflareinsights.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data: blob:; font-src 'self' data: https://fonts.gstatic.com; connect-src 'self' https://cloudflareinsights.com https://challenges.cloudflare.com; frame-src 'self' https://challenges.cloudflare.com; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'`
  * Other Info: `style-src includes unsafe-inline.`
* URL: http://127.0.0.1:8130/kg-api/api/vnc-auth/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/vnc-auth/`
  * Method: `GET`
  * Parameter: `Content-Security-Policy`
  * Attack: ``
  * Evidence: `default-src 'self'; script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com https://static.cloudflareinsights.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data: blob:; font-src 'self' data: https://fonts.gstatic.com; connect-src 'self' https://cloudflareinsights.com https://challenges.cloudflare.com; frame-src 'self' https://challenges.cloudflare.com; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'`
  * Other Info: `style-src includes unsafe-inline.`
* URL: http://127.0.0.1:8130/kg-api/api/invite/x/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/invite/x/ ()({password})`
  * Method: `POST`
  * Parameter: `Content-Security-Policy`
  * Attack: ``
  * Evidence: `default-src 'self'; script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com https://static.cloudflareinsights.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data: blob:; font-src 'self' data: https://fonts.gstatic.com; connect-src 'self' https://cloudflareinsights.com https://challenges.cloudflare.com; frame-src 'self' https://challenges.cloudflare.com; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'`
  * Other Info: `style-src includes unsafe-inline.`


Instances: 5

### Solution

Ensure that your web server, application server, load balancer, etc. is properly configured to set the Content-Security-Policy header.

### Reference


* [ https://www.w3.org/TR/CSP/ ](https://www.w3.org/TR/CSP/)
* [ https://caniuse.com/#search=content+security+policy ](https://caniuse.com/#search=content+security+policy)
* [ https://content-security-policy.com/ ](https://content-security-policy.com/)
* [ https://github.com/HtmlUnit/htmlunit-csp ](https://github.com/HtmlUnit/htmlunit-csp)
* [ https://web.dev/articles/csp#resource-options ](https://web.dev/articles/csp#resource-options)


#### CWE Id: [ 693 ](https://cwe.mitre.org/data/definitions/693.html)


#### WASC Id: 15

#### Source ID: 3

### [ Cross-Origin-Embedder-Policy Header Missing or Invalid ](https://www.zaproxy.org/docs/alerts/90004/)



##### Low (Medium)

### Description

Cross-Origin-Embedder-Policy header is a response header that prevents a document from loading any cross-origin resources that don't explicitly grant the document permission (using CORP or CORS).

* URL: http://127.0.0.1:8130/kg-api/api/media-auth/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/media-auth/`
  * Method: `GET`
  * Parameter: `Cross-Origin-Embedder-Policy`
  * Attack: ``
  * Evidence: ``
  * Other Info: ``


Instances: 1

### Solution

Ensure that the application/web server sets the Cross-Origin-Embedder-Policy header appropriately, and that it sets the Cross-Origin-Embedder-Policy header to 'require-corp' for documents.
If possible, ensure that the end user uses a standards-compliant and modern web browser that supports the Cross-Origin-Embedder-Policy header (https://caniuse.com/mdn-http_headers_cross-origin-embedder-policy).

### Reference


* [ https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Cross-Origin-Embedder-Policy ](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Cross-Origin-Embedder-Policy)


#### CWE Id: [ 693 ](https://cwe.mitre.org/data/definitions/693.html)


#### WASC Id: 14

#### Source ID: 3

### [ Unexpected Content-Type was returned ](https://www.zaproxy.org/docs/alerts/100001/)



##### Low (High)

### Description

A Content-Type of text/html was returned by the server.
This is not one of the types expected to be returned by an API.
Raised by the 'Alert on Unexpected Content Types' script

* URL: http://127.0.0.1:8130
  * Node Name: `http://127.0.0.1:8130`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/html`
  * Other Info: ``
* URL: http://127.0.0.1:8130/
  * Node Name: `http://127.0.0.1:8130/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/html`
  * Other Info: ``
* URL: http://127.0.0.1:8130/1357444200388016700
  * Node Name: `http://127.0.0.1:8130/1357444200388016700`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/html`
  * Other Info: ``
* URL: http://127.0.0.1:8130/7687322987418052976
  * Node Name: `http://127.0.0.1:8130/7687322987418052976`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/html`
  * Other Info: ``
* URL: http://127.0.0.1:8130/Toyota/2025/1324656364141298873
  * Node Name: `http://127.0.0.1:8130/Toyota/2025/1324656364141298873`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/html`
  * Other Info: ``
* URL: http://127.0.0.1:8130/Toyota/2025/2604667812767378316
  * Node Name: `http://127.0.0.1:8130/Toyota/2025/2604667812767378316`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/html`
  * Other Info: ``
* URL: http://127.0.0.1:8130/Toyota/2025/4327963923563575231
  * Node Name: `http://127.0.0.1:8130/Toyota/2025/4327963923563575231`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/html`
  * Other Info: ``
* URL: http://127.0.0.1:8130/Toyota/2025/5456861108869616225
  * Node Name: `http://127.0.0.1:8130/Toyota/2025/5456861108869616225`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/html`
  * Other Info: ``
* URL: http://127.0.0.1:8130/Toyota/742538007232261763
  * Node Name: `http://127.0.0.1:8130/Toyota/742538007232261763`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/html`
  * Other Info: ``
* URL: http://127.0.0.1:8130/Toyota/7585234352835102562
  * Node Name: `http://127.0.0.1:8130/Toyota/7585234352835102562`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/html`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api
  * Node Name: `http://127.0.0.1:8130/kg-api`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/html`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/7687322987418052976
  * Node Name: `http://127.0.0.1:8130/kg-api/7687322987418052976`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/html`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/Toyota
  * Node Name: `http://127.0.0.1:8130/kg-api/Toyota`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/html`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/Toyota/2025
  * Node Name: `http://127.0.0.1:8130/kg-api/Toyota/2025`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/html`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/Toyota/2025/1324656364141298873
  * Node Name: `http://127.0.0.1:8130/kg-api/Toyota/2025/1324656364141298873`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/html`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/Toyota/2025/5456861108869616225
  * Node Name: `http://127.0.0.1:8130/kg-api/Toyota/2025/5456861108869616225`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/html`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/Toyota/2025/Corolla%2520Cross%2520Hybrid%2520S
  * Node Name: `http://127.0.0.1:8130/kg-api/Toyota/2025/Corolla Cross Hybrid S`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/html`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/Toyota/7585234352835102562
  * Node Name: `http://127.0.0.1:8130/kg-api/Toyota/7585234352835102562`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/html`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api
  * Node Name: `http://127.0.0.1:8130/kg-api/api`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/html`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/events/stream
  * Node Name: `http://127.0.0.1:8130/kg-api/api/events/stream`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/html`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/grafana-auth/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/grafana-auth/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/html`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/labor-times/Toyota/2025/Corolla%2520Cross%2520Hybrid%2520S/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/labor-times/Toyota/2025/Corolla Cross Hybrid S/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/csv`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/media-auth/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/media-auth/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/html`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/metrics/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/metrics/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/html`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/sst/Toyota/2025/Corolla%2520Cross%2520Hybrid%2520S/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/sst/Toyota/2025/Corolla Cross Hybrid S/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/csv`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/sst/Toyota/2025/Corolla%2520Cross%2520Hybrid%2520S/%3Fprobe=
  * Node Name: `http://127.0.0.1:8130/kg-api/api/sst/Toyota/2025/Corolla Cross Hybrid S/ (probe)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/csv`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/team/report/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/team/report/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `application/pdf`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/team/report/%3Frange=http%253A%252F%252Fwww.google.com%252F
  * Node Name: `http://127.0.0.1:8130/kg-api/api/team/report/ (range)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `application/pdf`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/vnc-auth/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/vnc-auth/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/html`
  * Other Info: ``
* URL: http://127.0.0.1:8130/metadata/instance
  * Node Name: `http://127.0.0.1:8130/metadata/instance`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/html`
  * Other Info: ``
* URL: http://127.0.0.1:8130/metadata/v1
  * Node Name: `http://127.0.0.1:8130/metadata/v1`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/html`
  * Other Info: ``
* URL: http://127.0.0.1:8130/openstack/latest/meta_data.json
  * Node Name: `http://127.0.0.1:8130/openstack/latest/meta_data.json`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/html`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/invite/x/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/invite/x/ ()({password})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `text/html`
  * Other Info: ``


Instances: 33

### Solution



### Reference




#### Source ID: 4

### [ A Client Error response code was returned by the server ](https://www.zaproxy.org/docs/alerts/100000/)



##### Informational (High)

### Description

A response code of 403 was returned by the server.
This may indicate that the application is failing to handle unexpected input correctly.
Raised by the 'Alert on HTTP Response Code Error' script

* URL: http://127.0.0.1:8130/kg-api/api/org/nodes/1/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/org/nodes/1/`
  * Method: `DELETE`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/1357444200388016700
  * Node Name: `http://127.0.0.1:8130/1357444200388016700`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/7687322987418052976
  * Node Name: `http://127.0.0.1:8130/7687322987418052976`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/Toyota/742538007232261763
  * Node Name: `http://127.0.0.1:8130/Toyota/742538007232261763`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/Toyota/7585234352835102562
  * Node Name: `http://127.0.0.1:8130/Toyota/7585234352835102562`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/7687322987418052976
  * Node Name: `http://127.0.0.1:8130/kg-api/7687322987418052976`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/Toyota/2025/Corolla%2520Cross%2520Hybrid%2520S
  * Node Name: `http://127.0.0.1:8130/kg-api/Toyota/2025/Corolla Cross Hybrid S`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/Toyota/2025/Corolla%2520Cross%2520Hybrid%2520S/
  * Node Name: `http://127.0.0.1:8130/kg-api/Toyota/2025/Corolla Cross Hybrid S/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/Toyota/2025/Corolla%2520Cross%2520Hybrid%2520S/%3Fseg=%255B%2522Engine%2522%255D&href=x&page=x&q=oil&limit=30&spec=1&subtree=1&max=100&nav=1
  * Node Name: `http://127.0.0.1:8130/kg-api/Toyota/2025/Corolla Cross Hybrid S/ (href,limit,max,nav,page,q,seg,spec,subtree)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/Toyota/2025/Corolla%2520Cross%2520Hybrid%2520S/%3Fseg=%255B%2522Engine%2522%255D&href=x&page=x&q=oil&limit=30&spec=1%253Bget-help+%2523&subtree=1&max=100&nav=1
  * Node Name: `http://127.0.0.1:8130/kg-api/Toyota/2025/Corolla Cross Hybrid S/ (href,limit,max,nav,page,q,seg,spec,subtree)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/Toyota/2025/Corolla%2520Cross%2520Hybrid%2520S/694653114150344654
  * Node Name: `http://127.0.0.1:8130/kg-api/Toyota/2025/Corolla Cross Hybrid S/694653114150344654`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/Toyota/7585234352835102562
  * Node Name: `http://127.0.0.1:8130/kg-api/Toyota/7585234352835102562`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/8256256952805654880
  * Node Name: `http://127.0.0.1:8130/kg-api/api/8256256952805654880`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/activity
  * Node Name: `http://127.0.0.1:8130/kg-api/api/activity`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/activity/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/activity/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `405`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/activity/2790130390585198936
  * Node Name: `http://127.0.0.1:8130/kg-api/api/activity/2790130390585198936`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/7755944071789394171
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/7755944071789394171`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/activity
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/activity`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/activity/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/activity/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/activity/%3Flimit=200&user_id=1&company_id=1&category=x
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/activity/ (category,company_id,limit,user_id)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/activity/3721702394257857690
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/activity/3721702394257857690`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/analytics
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/analytics`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/analytics/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/analytics/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/analytics/%3Frange=30&company_id=1
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/analytics/ (company_id,range)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/analytics/1791139587037933006
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/analytics/1791139587037933006`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/audit
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/audit`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/audit/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/audit/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/audit/%3Faction=x&actor=x&outcome=x&company_id=1&target_id=x&before_id=1&limit=50
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/audit/ (action,actor,before_id,company_id,limit,outcome,target_id)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/audit/4092814159246768919
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/audit/4092814159246768919`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/cars
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/cars`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/cars/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/cars/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/cars/5940838172258457681
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/cars/5940838172258457681`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/chat-logs
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/chat-logs`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/chat-logs/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/chat-logs/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/chat-logs/%3Fq=oil&user_id=1&page=1&company_id=1
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/chat-logs/ (company_id,page,q,user_id)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/chat-logs/269035048552851610
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/chat-logs/269035048552851610`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/companies
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/companies`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/companies/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/companies/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/companies/1
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/companies/1`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/companies/1/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/companies/1/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/companies/1/7704842582213587710
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/companies/1/7704842582213587710`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/companies/1/access
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/companies/1/access`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/companies/1/access/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/companies/1/access/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/companies/1/access/1537224195062539338
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/companies/1/access/1537224195062539338`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/companies/1/roles
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/companies/1/roles`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/companies/1/roles/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/companies/1/roles/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/companies/1/roles/8531677577777936936
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/companies/1/roles/8531677577777936936`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/companies/1/roles/delete
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/companies/1/roles/delete`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/companies/1/roles/delete/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/companies/1/roles/delete/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/companies/1/roles/delete/4619111743675805954
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/companies/1/roles/delete/4619111743675805954`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/companies/7449015906233873614
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/companies/7449015906233873614`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/company-requests
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/company-requests`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/company-requests/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/company-requests/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/company-requests/%3Fstatus=pending&company_id=1
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/company-requests/ (company_id,status)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/company-requests/1
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/company-requests/1`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/company-requests/1/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/company-requests/1/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/company-requests/1/6037783370631344929
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/company-requests/1/6037783370631344929`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/company-requests/8330510556597058643
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/company-requests/8330510556597058643`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/dashboard
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/dashboard`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/dashboard/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/dashboard/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/dashboard/6775353955792244906
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/dashboard/6775353955792244906`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/data-quality
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/data-quality`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/data-quality/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/data-quality/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/data-quality/3503514861357816901
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/data-quality/3503514861357816901`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/flags
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/flags`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/flags/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/flags/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/flags/1195206103677287099
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/flags/1195206103677287099`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/flags/x
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/flags/x`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/flags/x/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/flags/x/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/flags/x/6315827514960366068
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/flags/x/6315827514960366068`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/flags/x/results
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/flags/x/results`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/flags/x/results/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/flags/x/results/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/flags/x/results/%3Fdays=30&exclude_companies=1,2
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/flags/x/results/ (days,exclude_companies)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/flags/x/results/7752600957802517995
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/flags/x/results/7752600957802517995`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/grafana-ticket
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/grafana-ticket`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/grafana-ticket/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/grafana-ticket/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/grafana-ticket/6950724297407874256
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/grafana-ticket/6950724297407874256`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/insights
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/insights`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/insights/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/insights/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/insights/5341561222178041147
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/insights/5341561222178041147`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/insights/ai-cost
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/insights/ai-cost`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/insights/ai-cost/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/insights/ai-cost/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/insights/ai-cost/%3Fdays=30
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/insights/ai-cost/ (days)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/insights/ai-cost/764346690133056573
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/insights/ai-cost/764346690133056573`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/insights/assistant
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/insights/assistant`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/insights/assistant/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/insights/assistant/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/insights/assistant/%3Fsession=x&log=1
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/insights/assistant/ (log,session)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/insights/assistant/9056037463288833731
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/insights/assistant/9056037463288833731`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/insights/funnel
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/insights/funnel`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/insights/funnel/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/insights/funnel/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/insights/funnel/5108193459025377433
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/insights/funnel/5108193459025377433`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/insights/search
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/insights/search`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/insights/search/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/insights/search/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/insights/search/%3Fcar=Corolla%2520Cross%2520Hybrid%2520S&company_id=1
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/insights/search/ (car,company_id)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/insights/search/3121518366305017249
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/insights/search/3121518366305017249`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/login
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/login`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/login/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/login/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `405`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/login/4164431993060203260
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/login/4164431993060203260`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/org
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/org`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/org/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/org/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/org/5689853336747361613
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/org/5689853336747361613`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/org/reassign-root
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/org/reassign-root`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/org/reassign-root/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/org/reassign-root/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/org/reassign-root/6721700967786033425
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/org/reassign-root/6721700967786033425`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/overview
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/overview`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/overview/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/overview/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/overview/2013409928328214177
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/overview/2013409928328214177`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/packages
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/packages`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/packages/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/packages/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/packages/801860964271730417
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/packages/801860964271730417`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/parts
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/parts`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/parts/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/parts/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/parts/7808580184054621870
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/parts/7808580184054621870`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/pipeline
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/pipeline`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/pipeline/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/pipeline/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/pipeline/167971428608896612
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/pipeline/167971428608896612`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/processing-snapshot
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/processing-snapshot`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/processing-snapshot/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/processing-snapshot/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/processing-snapshot/303598392346460667
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/processing-snapshot/303598392346460667`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/requests
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/requests`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/requests/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/requests/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/requests/1
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/requests/1`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/requests/1/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/requests/1/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/requests/1/8354782502716711855
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/requests/1/8354782502716711855`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/requests/1/delete
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/requests/1/delete`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/requests/1/delete/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/requests/1/delete/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/requests/1/delete/5595028341047071515
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/requests/1/delete/5595028341047071515`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/requests/1/status
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/requests/1/status`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/requests/1/status/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/requests/1/status/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/requests/1/status/7844767461247387985
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/requests/1/status/7844767461247387985`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/requests/139410381610010070
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/requests/139410381610010070`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/system
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/system`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/system/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/system/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/system/5393413758471321058
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/system/5393413758471321058`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/traffic
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/traffic`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/traffic/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/traffic/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/traffic/%3Frange=7
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/traffic/ (range)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/traffic/8044928946737472936
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/traffic/8044928946737472936`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/users
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/users`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/users/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/users/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/users/%3Fcompany_id=1
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/users/ (company_id)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/users/1
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/users/1`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/users/1/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/users/1/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/users/1/3014822181149845536
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/users/1/3014822181149845536`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/users/1/access
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/users/1/access`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/users/1/access/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/users/1/access/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/users/1/access/4334215801722891960
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/users/1/access/4334215801722891960`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/users/4439047032462330374
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/users/4439047032462330374`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/vehicle-specs
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/vehicle-specs`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/vehicle-specs/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/vehicle-specs/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/vehicle-specs/%3Fcar_id=1
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/vehicle-specs/ (car_id)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/vehicle-specs/8076546114018290982
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/vehicle-specs/8076546114018290982`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/verify-otp
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/verify-otp`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/verify-otp/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/verify-otp/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/verify-otp/2002066175568286332
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/verify-otp/2002066175568286332`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/assist
  * Node Name: `http://127.0.0.1:8130/kg-api/api/assist`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/assist/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/assist/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/assist/%3F=&brand=Toyota&model=Corolla+Cross+Hybrid+S&car=Corolla+Cross+Hybrid+S
  * Node Name: `http://127.0.0.1:8130/kg-api/api/assist/ (brand,car,model)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `400`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/assist/%3Fq=engine+oil+capacity&brand=Toyota&model=www.google.com%252Fsearch%253Fq%253DZAP&car=Corolla+Cross+Hybrid+S
  * Node Name: `http://127.0.0.1:8130/kg-api/api/assist/ (brand,car,model,q)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/assist/5556684072322471411
  * Node Name: `http://127.0.0.1:8130/kg-api/api/assist/5556684072322471411`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/assist/feedback
  * Node Name: `http://127.0.0.1:8130/kg-api/api/assist/feedback`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/assist/feedback/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/assist/feedback/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `405`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/assist/feedback/4354652107777562185
  * Node Name: `http://127.0.0.1:8130/kg-api/api/assist/feedback/4354652107777562185`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/5281008577366376258
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/5281008577366376258`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/ai-usage
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/ai-usage`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/ai-usage/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/ai-usage/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/ai-usage/4395544368171912053
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/ai-usage/4395544368171912053`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/chat-feedback
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/chat-feedback`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/chat-feedback/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/chat-feedback/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `405`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/chat-feedback/7069439758342903968
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/chat-feedback/7069439758342903968`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/chat-log
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/chat-log`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/chat-log/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/chat-log/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `405`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/chat-log/6792387943212284967
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/chat-log/6792387943212284967`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/flags
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/flags`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/flags/3207246844377151956
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/flags/3207246844377151956`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/fleet
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/fleet`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/fleet/5608627760278718533
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/fleet/5608627760278718533`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/login
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/login`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/login/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/login/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/login/8463407926295773508
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/login/8463407926295773508`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/me
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/me`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/me/1836979544600427222
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/me/1836979544600427222`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/me/prefs
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/me/prefs`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/me/prefs/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/me/prefs/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `405`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/me/prefs/7680952022902994220
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/me/prefs/7680952022902994220`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/recover
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/recover`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/recover/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/recover/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/recover/6333705769974997335
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/recover/6333705769974997335`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/recover/reset
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/recover/reset`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/recover/reset/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/recover/reset/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/recover/reset/3992356402284167414
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/recover/reset/3992356402284167414`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/recover/start
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/recover/start`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/recover/start/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/recover/start/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/recover/start/3684951206475115567
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/recover/start/3684951206475115567`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/resend-otp
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/resend-otp`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/resend-otp/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/resend-otp/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/resend-otp/2319993378339125564
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/resend-otp/2319993378339125564`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/verify-otp
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/verify-otp`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/verify-otp/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/verify-otp/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/verify-otp/4141308065472735469
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/verify-otp/4141308065472735469`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/company
  * Node Name: `http://127.0.0.1:8130/kg-api/api/company`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/company/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/company/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/company/7907799445832332006
  * Node Name: `http://127.0.0.1:8130/kg-api/api/company/7907799445832332006`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/company/requests
  * Node Name: `http://127.0.0.1:8130/kg-api/api/company/requests`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/company/requests/1
  * Node Name: `http://127.0.0.1:8130/kg-api/api/company/requests/1`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/company/requests/1/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/company/requests/1/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/company/requests/1/3846435467517513241
  * Node Name: `http://127.0.0.1:8130/kg-api/api/company/requests/1/3846435467517513241`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/company/requests/8619034457475416423
  * Node Name: `http://127.0.0.1:8130/kg-api/api/company/requests/8619034457475416423`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/diagnose
  * Node Name: `http://127.0.0.1:8130/kg-api/api/diagnose`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/diagnose/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/diagnose/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `400`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/diagnose/%3Fq=engine+oil+capacity&brand=Toyota&model=Corolla+Cross+Hybrid+S&car=www.google.com%252F
  * Node Name: `http://127.0.0.1:8130/kg-api/api/diagnose/ (brand,car,model,q)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/diagnose/3509264373759853359
  * Node Name: `http://127.0.0.1:8130/kg-api/api/diagnose/3509264373759853359`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/eval
  * Node Name: `http://127.0.0.1:8130/kg-api/api/eval`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/eval/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/eval/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/eval/7073469352755518513
  * Node Name: `http://127.0.0.1:8130/kg-api/api/eval/7073469352755518513`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/eval/report
  * Node Name: `http://127.0.0.1:8130/kg-api/api/eval/report`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/eval/report/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/eval/report/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/eval/report/4727729351213656267
  * Node Name: `http://127.0.0.1:8130/kg-api/api/eval/report/4727729351213656267`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/events
  * Node Name: `http://127.0.0.1:8130/kg-api/api/events`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/events/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/events/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/events/6124539308406219651
  * Node Name: `http://127.0.0.1:8130/kg-api/api/events/6124539308406219651`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/events/recent
  * Node Name: `http://127.0.0.1:8130/kg-api/api/events/recent`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/events/recent/120408114347824793
  * Node Name: `http://127.0.0.1:8130/kg-api/api/events/recent/120408114347824793`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/feedback
  * Node Name: `http://127.0.0.1:8130/kg-api/api/feedback`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/feedback/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/feedback/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/feedback/163942528610570927
  * Node Name: `http://127.0.0.1:8130/kg-api/api/feedback/163942528610570927`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/feedback/pin
  * Node Name: `http://127.0.0.1:8130/kg-api/api/feedback/pin`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/feedback/pin/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/feedback/pin/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/feedback/pin/2681074981104820664
  * Node Name: `http://127.0.0.1:8130/kg-api/api/feedback/pin/2681074981104820664`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/feedback/rate
  * Node Name: `http://127.0.0.1:8130/kg-api/api/feedback/rate`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/feedback/rate/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/feedback/rate/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `405`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/feedback/rate/989989021655211938
  * Node Name: `http://127.0.0.1:8130/kg-api/api/feedback/rate/989989021655211938`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/feedback/recent
  * Node Name: `http://127.0.0.1:8130/kg-api/api/feedback/recent`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/feedback/recent/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/feedback/recent/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/feedback/recent/%3Flimit=50
  * Node Name: `http://127.0.0.1:8130/kg-api/api/feedback/recent/ (limit)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/feedback/recent/728714143037646692
  * Node Name: `http://127.0.0.1:8130/kg-api/api/feedback/recent/728714143037646692`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/frm
  * Node Name: `http://127.0.0.1:8130/kg-api/api/frm`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/frm/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/frm/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/frm/820200560009868238
  * Node Name: `http://127.0.0.1:8130/kg-api/api/frm/820200560009868238`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/frm/x
  * Node Name: `http://127.0.0.1:8130/kg-api/api/frm/x`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/frm/x
  * Node Name: `http://127.0.0.1:8130/kg-api/api/frm/x`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/frm/x/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/frm/x/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/frm/x/%3Fpart=lts
  * Node Name: `http://127.0.0.1:8130/kg-api/api/frm/x/ (part)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/frm/x/%3Fpart=%2522%2527
  * Node Name: `http://127.0.0.1:8130/kg-api/api/frm/x/ (part)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/frm/x/4773473723671437051
  * Node Name: `http://127.0.0.1:8130/kg-api/api/frm/x/4773473723671437051`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/grafana-auth
  * Node Name: `http://127.0.0.1:8130/kg-api/api/grafana-auth`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/grafana-auth/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/grafana-auth/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/grafana-auth/2309216886796556918
  * Node Name: `http://127.0.0.1:8130/kg-api/api/grafana-auth/2309216886796556918`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/health
  * Node Name: `http://127.0.0.1:8130/kg-api/api/health`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/health/3951291564778103694
  * Node Name: `http://127.0.0.1:8130/kg-api/api/health/3951291564778103694`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/invite
  * Node Name: `http://127.0.0.1:8130/kg-api/api/invite`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/invite/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/invite/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/invite/8996670380232395205
  * Node Name: `http://127.0.0.1:8130/kg-api/api/invite/8996670380232395205`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/invite/x
  * Node Name: `http://127.0.0.1:8130/kg-api/api/invite/x`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/invite/x/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/invite/x/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `400`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/invite/x/8370964059106554821
  * Node Name: `http://127.0.0.1:8130/kg-api/api/invite/x/8370964059106554821`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/labor-times
  * Node Name: `http://127.0.0.1:8130/kg-api/api/labor-times`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/labor-times/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/labor-times/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/labor-times/7029749419274002764
  * Node Name: `http://127.0.0.1:8130/kg-api/api/labor-times/7029749419274002764`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/labor-times/Toyota
  * Node Name: `http://127.0.0.1:8130/kg-api/api/labor-times/Toyota`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/labor-times/Toyota
  * Node Name: `http://127.0.0.1:8130/kg-api/api/labor-times/Toyota`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/labor-times/Toyota/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/labor-times/Toyota/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/labor-times/Toyota/2025
  * Node Name: `http://127.0.0.1:8130/kg-api/api/labor-times/Toyota/2025`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/labor-times/Toyota/2025
  * Node Name: `http://127.0.0.1:8130/kg-api/api/labor-times/Toyota/2025`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/labor-times/Toyota/2025/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/labor-times/Toyota/2025/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/labor-times/Toyota/2025/651159102258049246
  * Node Name: `http://127.0.0.1:8130/kg-api/api/labor-times/Toyota/2025/651159102258049246`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/labor-times/Toyota/2025/Corolla%2520Cross%2520Hybrid%2520S
  * Node Name: `http://127.0.0.1:8130/kg-api/api/labor-times/Toyota/2025/Corolla Cross Hybrid S`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/labor-times/Toyota/2025/Corolla%2520Cross%2520Hybrid%2520S
  * Node Name: `http://127.0.0.1:8130/kg-api/api/labor-times/Toyota/2025/Corolla Cross Hybrid S`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/labor-times/Toyota/2025/Corolla%2520Cross%2520Hybrid%2520S/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/labor-times/Toyota/2025/Corolla Cross Hybrid S/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/labor-times/Toyota/2025/Corolla%2520Cross%2520Hybrid%2520S/3668515541914741164
  * Node Name: `http://127.0.0.1:8130/kg-api/api/labor-times/Toyota/2025/Corolla Cross Hybrid S/3668515541914741164`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/labor-times/Toyota/2741990169984659914
  * Node Name: `http://127.0.0.1:8130/kg-api/api/labor-times/Toyota/2741990169984659914`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/media-auth
  * Node Name: `http://127.0.0.1:8130/kg-api/api/media-auth`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/media-auth/3679146329641565895
  * Node Name: `http://127.0.0.1:8130/kg-api/api/media-auth/3679146329641565895`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/metrics
  * Node Name: `http://127.0.0.1:8130/kg-api/api/metrics`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/metrics/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/metrics/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/metrics/4303974274653293699
  * Node Name: `http://127.0.0.1:8130/kg-api/api/metrics/4303974274653293699`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/org
  * Node Name: `http://127.0.0.1:8130/kg-api/api/org`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/org/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/org/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/org/3537605283857845131
  * Node Name: `http://127.0.0.1:8130/kg-api/api/org/3537605283857845131`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/org/graph
  * Node Name: `http://127.0.0.1:8130/kg-api/api/org/graph`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/org/graph/6600495761627898035
  * Node Name: `http://127.0.0.1:8130/kg-api/api/org/graph/6600495761627898035`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/org/nodes
  * Node Name: `http://127.0.0.1:8130/kg-api/api/org/nodes`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/org/nodes/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/org/nodes/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `405`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/org/nodes/1
  * Node Name: `http://127.0.0.1:8130/kg-api/api/org/nodes/1`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/org/nodes/1/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/org/nodes/1/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/org/nodes/1/1546434732713294729
  * Node Name: `http://127.0.0.1:8130/kg-api/api/org/nodes/1/1546434732713294729`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/org/nodes/1/create-user
  * Node Name: `http://127.0.0.1:8130/kg-api/api/org/nodes/1/create-user`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/org/nodes/1/create-user/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/org/nodes/1/create-user/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `405`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/org/nodes/1/create-user/6509760011051663751
  * Node Name: `http://127.0.0.1:8130/kg-api/api/org/nodes/1/create-user/6509760011051663751`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/org/nodes/1/permission
  * Node Name: `http://127.0.0.1:8130/kg-api/api/org/nodes/1/permission`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/org/nodes/1/permission/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/org/nodes/1/permission/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `405`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/org/nodes/1/permission/3309935921210966635
  * Node Name: `http://127.0.0.1:8130/kg-api/api/org/nodes/1/permission/3309935921210966635`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/org/nodes/2454310009592552239
  * Node Name: `http://127.0.0.1:8130/kg-api/api/org/nodes/2454310009592552239`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/parts
  * Node Name: `http://127.0.0.1:8130/kg-api/api/parts`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/parts/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/parts/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/parts/2329503190944194661
  * Node Name: `http://127.0.0.1:8130/kg-api/api/parts/2329503190944194661`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/parts/Toyota
  * Node Name: `http://127.0.0.1:8130/kg-api/api/parts/Toyota`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/parts/Toyota
  * Node Name: `http://127.0.0.1:8130/kg-api/api/parts/Toyota`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/parts/Toyota/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/parts/Toyota/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/parts/Toyota/2025
  * Node Name: `http://127.0.0.1:8130/kg-api/api/parts/Toyota/2025`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/parts/Toyota/2025
  * Node Name: `http://127.0.0.1:8130/kg-api/api/parts/Toyota/2025`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/parts/Toyota/2025/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/parts/Toyota/2025/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/parts/Toyota/2025/4016272362223944809
  * Node Name: `http://127.0.0.1:8130/kg-api/api/parts/Toyota/2025/4016272362223944809`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/parts/Toyota/2025/Corolla%2520Cross%2520Hybrid%2520S
  * Node Name: `http://127.0.0.1:8130/kg-api/api/parts/Toyota/2025/Corolla Cross Hybrid S`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/parts/Toyota/2025/Corolla%2520Cross%2520Hybrid%2520S
  * Node Name: `http://127.0.0.1:8130/kg-api/api/parts/Toyota/2025/Corolla Cross Hybrid S`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/parts/Toyota/2025/Corolla%2520Cross%2520Hybrid%2520S/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/parts/Toyota/2025/Corolla Cross Hybrid S/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/parts/Toyota/2025/Corolla%2520Cross%2520Hybrid%2520S/%3Fcfg=x&seg=%255B%2522x%2522%255D
  * Node Name: `http://127.0.0.1:8130/kg-api/api/parts/Toyota/2025/Corolla Cross Hybrid S/ (cfg,seg)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/parts/Toyota/2025/Corolla%2520Cross%2520Hybrid%2520S/%3Fcfg=%2522%2527&seg=%255B%2522x%2522%255D
  * Node Name: `http://127.0.0.1:8130/kg-api/api/parts/Toyota/2025/Corolla Cross Hybrid S/ (cfg,seg)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/parts/Toyota/2025/Corolla%2520Cross%2520Hybrid%2520S/8722048669007255217
  * Node Name: `http://127.0.0.1:8130/kg-api/api/parts/Toyota/2025/Corolla Cross Hybrid S/8722048669007255217`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/parts/Toyota/7161939899158904008
  * Node Name: `http://127.0.0.1:8130/kg-api/api/parts/Toyota/7161939899158904008`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/purchase-request
  * Node Name: `http://127.0.0.1:8130/kg-api/api/purchase-request`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/purchase-request/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/purchase-request/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/purchase-request/2592486354400088701
  * Node Name: `http://127.0.0.1:8130/kg-api/api/purchase-request/2592486354400088701`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/recommendations
  * Node Name: `http://127.0.0.1:8130/kg-api/api/recommendations`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/recommendations/1153894163212069832
  * Node Name: `http://127.0.0.1:8130/kg-api/api/recommendations/1153894163212069832`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/search
  * Node Name: `http://127.0.0.1:8130/kg-api/api/search`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/search/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/search/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/search/%3Fq=engine%2520oil&brand=Toyota&model=Corolla%2520Cross%2520Hybrid%2520S&car=Corolla%2520Cross%2520Hybrid%2520S&limit=30
  * Node Name: `http://127.0.0.1:8130/kg-api/api/search/ (brand,car,limit,model,q)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/search/7716472241905371432
  * Node Name: `http://127.0.0.1:8130/kg-api/api/search/7716472241905371432`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/shield
  * Node Name: `http://127.0.0.1:8130/kg-api/api/shield`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/shield/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/shield/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/shield/2141810138937154912
  * Node Name: `http://127.0.0.1:8130/kg-api/api/shield/2141810138937154912`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/shield/key
  * Node Name: `http://127.0.0.1:8130/kg-api/api/shield/key`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/shield/key/%3Fe=1
  * Node Name: `http://127.0.0.1:8130/kg-api/api/shield/key/ (e)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `400`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/shield/key/8207283458114955661
  * Node Name: `http://127.0.0.1:8130/kg-api/api/shield/key/8207283458114955661`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/sst
  * Node Name: `http://127.0.0.1:8130/kg-api/api/sst`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/sst/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/sst/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/sst/4732356118006703828
  * Node Name: `http://127.0.0.1:8130/kg-api/api/sst/4732356118006703828`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/sst/Toyota
  * Node Name: `http://127.0.0.1:8130/kg-api/api/sst/Toyota`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/sst/Toyota/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/sst/Toyota/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/sst/Toyota/2025
  * Node Name: `http://127.0.0.1:8130/kg-api/api/sst/Toyota/2025`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/sst/Toyota/2025/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/sst/Toyota/2025/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/sst/Toyota/2025/8856423694952780938
  * Node Name: `http://127.0.0.1:8130/kg-api/api/sst/Toyota/2025/8856423694952780938`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/sst/Toyota/2025/Corolla%2520Cross%2520Hybrid%2520S
  * Node Name: `http://127.0.0.1:8130/kg-api/api/sst/Toyota/2025/Corolla Cross Hybrid S`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/sst/Toyota/2025/Corolla%2520Cross%2520Hybrid%2520S/2536932632595967558
  * Node Name: `http://127.0.0.1:8130/kg-api/api/sst/Toyota/2025/Corolla Cross Hybrid S/2536932632595967558`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/sst/Toyota/6851450999037505604
  * Node Name: `http://127.0.0.1:8130/kg-api/api/sst/Toyota/6851450999037505604`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/team
  * Node Name: `http://127.0.0.1:8130/kg-api/api/team`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/team/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/team/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/team/4238500648860799541
  * Node Name: `http://127.0.0.1:8130/kg-api/api/team/4238500648860799541`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/team/analytics
  * Node Name: `http://127.0.0.1:8130/kg-api/api/team/analytics`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/team/analytics/%3Frange=30&member_id=1&category=x
  * Node Name: `http://127.0.0.1:8130/kg-api/api/team/analytics/ (category,member_id,range)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/team/analytics/5060789676433834744
  * Node Name: `http://127.0.0.1:8130/kg-api/api/team/analytics/5060789676433834744`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/team/chat-logs
  * Node Name: `http://127.0.0.1:8130/kg-api/api/team/chat-logs`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/team/chat-logs/%3Fq=oil&user_id=1&page=1
  * Node Name: `http://127.0.0.1:8130/kg-api/api/team/chat-logs/ (page,q,user_id)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/team/chat-logs/4740477094747493483
  * Node Name: `http://127.0.0.1:8130/kg-api/api/team/chat-logs/4740477094747493483`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/team/insights
  * Node Name: `http://127.0.0.1:8130/kg-api/api/team/insights`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/team/insights/3399577491428248984
  * Node Name: `http://127.0.0.1:8130/kg-api/api/team/insights/3399577491428248984`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/team/report
  * Node Name: `http://127.0.0.1:8130/kg-api/api/team/report`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/team/report/%3Frange=30
  * Node Name: `http://127.0.0.1:8130/kg-api/api/team/report/ (range)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/team/report/6089596327068063807
  * Node Name: `http://127.0.0.1:8130/kg-api/api/team/report/6089596327068063807`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/vnc-auth
  * Node Name: `http://127.0.0.1:8130/kg-api/api/vnc-auth`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/vnc-auth/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/vnc-auth/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/vnc-auth/255530565669168171
  * Node Name: `http://127.0.0.1:8130/kg-api/api/vnc-auth/255530565669168171`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/vnc-auth/actuator/health
  * Node Name: `http://127.0.0.1:8130/kg-api/api/vnc-auth/actuator/health`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/metadata/instance
  * Node Name: `http://127.0.0.1:8130/metadata/instance`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/metadata/v1
  * Node Name: `http://127.0.0.1:8130/metadata/v1`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/org/nodes/1/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/org/nodes/1/ ()({label,parent_id})`
  * Method: `PATCH`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/companies/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/companies/ ()({})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/companies/1/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/companies/1/ ()({})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/companies/1/access/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/companies/1/access/ ()({accesses:[]})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/companies/1/roles/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/companies/1/roles/ ()({})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/companies/1/roles/delete/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/companies/1/roles/delete/ ()({})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/company-requests/1/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/company-requests/1/ ()({status,admin_note})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/data-quality/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/data-quality/ ()({refresh,fix})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/flags/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/flags/ ()({key,enabled,rollout_pct})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/grafana-ticket/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/grafana-ticket/`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/login/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/login/ ()({username,password})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/login/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/login/ ()({username,password})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/org/reassign-root/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/org/reassign-root/ ()({company_id,username})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/pipeline/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/pipeline/ ()({action})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/requests/1/delete/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/requests/1/delete/`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/requests/1/status/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/requests/1/status/ ()({status})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/system/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/system/ ()({action})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/users/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/users/ ()({})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/users/1/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/users/1/ ()({})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/users/1/access/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/users/1/access/ ()({})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/verify-otp/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/verify-otp/ ()({otp_session,code})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/verify-otp/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/verify-otp/ ()({otp_session,code})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/assist/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/assist/ ()({query,brand,model})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/assist/feedback/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/assist/feedback/ ()({query,blob_id,app_url})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/ai-usage/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/ai-usage/ ()({detail,car})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/chat-feedback/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/chat-feedback/ ()({key,kind,verdict})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `400`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/chat-feedback/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/chat-feedback/ ()({key,kind,verdict})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/chat-log/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/chat-log/ ()({question,answer,client_key})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `400`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/login/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/login/ ()({username,password,turnstile_token})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/login/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/login/ ()({username,password,turnstile_token})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/me/prefs/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/me/prefs/ ()({browse_mode})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `400`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/recover/reset/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/recover/reset/ ()({otp_session,code,new_password})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/recover/reset/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/recover/reset/ ()({otp_session,code,new_password})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/recover/start/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/recover/start/ ()({identifier,turnstile_token})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/recover/start/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/recover/start/ ()({identifier,turnstile_token})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/resend-otp/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/resend-otp/ ()({otp_session})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `400`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/resend-otp/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/resend-otp/ ()({otp_session})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/verify-otp/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/verify-otp/ ()({otp_session,code})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/auth/verify-otp/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/verify-otp/ ()({otp_session,code})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/company/requests/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/company/requests/ ()({kind,subject,body,priority})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `400`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/company/requests/1/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/company/requests/1/ ()({cancel})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/diagnose/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/diagnose/ ()({query,brand,model})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/feedback/pin/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/feedback/pin/ ()({pattern_query,app_url})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/feedback/rate/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/feedback/rate/ ()({query,verdict})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/invite/x/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/invite/x/ ()({password})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/org/nodes/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/org/nodes/ ()({label,parent_id,x,y})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `400`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/org/nodes/1/create-user/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/org/nodes/1/create-user/ ()({display_name,phone})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/org/nodes/1/permission/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/org/nodes/1/permission/ ()({car_access:[{car_id,documents:[]}],ai_eligible,admin_panels:[]})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `404`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/purchase-request/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/purchase-request/ ()({brand,model,year,documents:[],company,mobile})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `400`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/purchase-request/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/purchase-request/ ()({brand,model,year,documents:[],company,mobile})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `429`
  * Other Info: ``


Instances: 411

### Solution



### Reference



#### CWE Id: [ 388 ](https://cwe.mitre.org/data/definitions/388.html)


#### WASC Id: 20

#### Source ID: 4

### [ Authentication Request Identified ](https://www.zaproxy.org/docs/alerts/10111/)



##### Informational (High)

### Description

The given request has been identified as an authentication request. The 'Other Info' field contains a set of key=value lines which identify any relevant fields. If the request is in a context which has an Authentication Method set to "Auto-Detect" then this rule will change the authentication to match the request identified.

* URL: http://127.0.0.1:8130/kg-api/api/admin/login/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/login/ ()({username,password})`
  * Method: `POST`
  * Parameter: `username`
  * Attack: ``
  * Evidence: `password`
  * Other Info: `userParam=username
userValue=x
passwordParam=password`
* URL: http://127.0.0.1:8130/kg-api/api/auth/login/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/auth/login/ ()({username,password,turnstile_token})`
  * Method: `POST`
  * Parameter: `username`
  * Attack: ``
  * Evidence: `password`
  * Other Info: `userParam=username
userValue=x
passwordParam=password`


Instances: 2

### Solution

This is an informational alert rather than a vulnerability and so there is nothing to fix.

### Reference


* [ https://www.zaproxy.org/docs/desktop/addons/authentication-helper/auth-req-id/ ](https://www.zaproxy.org/docs/desktop/addons/authentication-helper/auth-req-id/)



#### Source ID: 3

### [ Information Disclosure - Sensitive Information in URL ](https://www.zaproxy.org/docs/alerts/10024/)



##### Informational (Medium)

### Description

The request appeared to contain sensitive information leaked in the URL. This can violate PCI and most organizational compliance policies. You can configure the list of strings for this check to add or remove values specific to your environment.

* URL: http://127.0.0.1:8130/kg-api/api/admin/activity/%3Flimit=200&user_id=1&company_id=1&category=x
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/activity/ (category,company_id,limit,user_id)`
  * Method: `GET`
  * Parameter: `user_id`
  * Attack: ``
  * Evidence: `user_id`
  * Other Info: `The URL contains potentially sensitive information. The following string was found via the pattern: user
user_id`
* URL: http://127.0.0.1:8130/kg-api/api/admin/chat-logs/%3Fq=oil&user_id=1&page=1&company_id=1
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/chat-logs/ (company_id,page,q,user_id)`
  * Method: `GET`
  * Parameter: `user_id`
  * Attack: ``
  * Evidence: `user_id`
  * Other Info: `The URL contains potentially sensitive information. The following string was found via the pattern: user
user_id`
* URL: http://127.0.0.1:8130/kg-api/api/admin/insights/assistant/%3Fsession=x&log=1
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/insights/assistant/ (log,session)`
  * Method: `GET`
  * Parameter: `session`
  * Attack: ``
  * Evidence: `session`
  * Other Info: `The URL contains potentially sensitive information. The following string was found via the pattern: session
session`
* URL: http://127.0.0.1:8130/kg-api/api/team/chat-logs/%3Fq=oil&user_id=1&page=1
  * Node Name: `http://127.0.0.1:8130/kg-api/api/team/chat-logs/ (page,q,user_id)`
  * Method: `GET`
  * Parameter: `user_id`
  * Attack: ``
  * Evidence: `user_id`
  * Other Info: `The URL contains potentially sensitive information. The following string was found via the pattern: user
user_id`


Instances: 4

### Solution

Do not pass sensitive information in URIs.

### Reference



#### CWE Id: [ 598 ](https://cwe.mitre.org/data/definitions/598.html)


#### WASC Id: 13

#### Source ID: 3

### [ Non-Storable Content ](https://www.zaproxy.org/docs/alerts/10049/)



##### Informational (Medium)

### Description

The response contents are not storable by caching components such as proxy servers. If the response does not contain sensitive, personal or user-specific information, it may benefit from being stored and cached, to improve performance.

* URL: http://127.0.0.1:8130/kg-api/api/admin/data-quality/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/data-quality/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/system/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/system/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/metrics/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/metrics/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `403`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/data-quality/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/data-quality/ ()({refresh,fix})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``
* URL: http://127.0.0.1:8130/kg-api/api/admin/system/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/admin/system/ ()({action})`
  * Method: `POST`
  * Parameter: ``
  * Attack: ``
  * Evidence: `401`
  * Other Info: ``

Instances: Systemic


### Solution

The content may be marked as storable by ensuring that the following conditions are satisfied:
The request method must be understood by the cache and defined as being cacheable ("GET", "HEAD", and "POST" are currently defined as cacheable)
The response status code must be understood by the cache (one of the 1XX, 2XX, 3XX, 4XX, or 5XX response classes are generally understood)
The "no-store" cache directive must not appear in the request or response header fields
For caching by "shared" caches such as "proxy" caches, the "private" response directive must not appear in the response
For caching by "shared" caches such as "proxy" caches, the "Authorization" header field must not appear in the request, unless the response explicitly allows it (using one of the "must-revalidate", "public", or "s-maxage" Cache-Control response directives)
In addition to the conditions above, at least one of the following conditions must also be satisfied by the response:
It must contain an "Expires" header field
It must contain a "max-age" response directive
For "shared" caches such as "proxy" caches, it must contain a "s-maxage" response directive
It must contain a "Cache Control Extension" that allows it to be cached
It must have a status code that is defined as cacheable by default (200, 203, 204, 206, 300, 301, 404, 405, 410, 414, 501).

### Reference


* [ https://datatracker.ietf.org/doc/html/rfc7234 ](https://datatracker.ietf.org/doc/html/rfc7234)
* [ https://datatracker.ietf.org/doc/html/rfc7231 ](https://datatracker.ietf.org/doc/html/rfc7231)
* [ https://www.w3.org/Protocols/rfc2616/rfc2616-sec13.html ](https://www.w3.org/Protocols/rfc2616/rfc2616-sec13.html)


#### CWE Id: [ 524 ](https://cwe.mitre.org/data/definitions/524.html)


#### WASC Id: 13

#### Source ID: 3

### [ Storable and Cacheable Content ](https://www.zaproxy.org/docs/alerts/10049/)



##### Informational (Medium)

### Description

The response contents are storable by caching components such as proxy servers, and may be retrieved directly from the cache, rather than from the origin server by the caching servers, in response to similar requests from other users. If the response data is sensitive, personal or user-specific, this may result in sensitive information being leaked. In some cases, this may even result in a user gaining complete control of the session of another user, depending on the configuration of the caching components in use in their environment. This is primarily an issue where "shared" caching servers such as "proxy" caches are configured on the local network. This configuration is typically found in corporate or educational environments, for instance.

* URL: http://127.0.0.1:8130/kg-api/api/events/recent/%3Fafter=0&limit=100
  * Node Name: `http://127.0.0.1:8130/kg-api/api/events/recent/ (after,limit)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: ``
  * Other Info: `In the absence of an explicitly specified caching lifetime directive in the response, a liberal lifetime heuristic of 1 year was assumed. This is permitted by rfc7234.`
* URL: http://127.0.0.1:8130/kg-api/api/health/
  * Node Name: `http://127.0.0.1:8130/kg-api/api/health/`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: ``
  * Other Info: `In the absence of an explicitly specified caching lifetime directive in the response, a liberal lifetime heuristic of 1 year was assumed. This is permitted by rfc7234.`


Instances: 2

### Solution

Validate that the response does not contain sensitive, personal or user-specific information. If it does, consider the use of the following HTTP response headers, to limit, or prevent the content being stored and retrieved from the cache by another user:
Cache-Control: no-cache, no-store, must-revalidate, private
Pragma: no-cache
Expires: 0
This configuration directs both HTTP 1.0 and HTTP 1.1 compliant caching servers to not store the response, and to not retrieve the response (without validation) from the cache, in response to a similar request.

### Reference


* [ https://datatracker.ietf.org/doc/html/rfc7234 ](https://datatracker.ietf.org/doc/html/rfc7234)
* [ https://datatracker.ietf.org/doc/html/rfc7231 ](https://datatracker.ietf.org/doc/html/rfc7231)
* [ https://www.w3.org/Protocols/rfc2616/rfc2616-sec13.html ](https://www.w3.org/Protocols/rfc2616/rfc2616-sec13.html)


#### CWE Id: [ 524 ](https://cwe.mitre.org/data/definitions/524.html)


#### WASC Id: 13

#### Source ID: 3

### [ Storable but Non-Cacheable Content ](https://www.zaproxy.org/docs/alerts/10049/)



##### Informational (Medium)

### Description

The response contents are storable by caching components such as proxy servers, but will not be retrieved directly from the cache, without validating the request upstream, in response to similar requests from other users.

* URL: http://127.0.0.1:8130/kg-api/api/events/stream/%3Fafter=0
  * Node Name: `http://127.0.0.1:8130/kg-api/api/events/stream/ (after)`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `no-cache`
  * Other Info: ``


Instances: 1

### Solution



### Reference


* [ https://datatracker.ietf.org/doc/html/rfc7234 ](https://datatracker.ietf.org/doc/html/rfc7234)
* [ https://datatracker.ietf.org/doc/html/rfc7231 ](https://datatracker.ietf.org/doc/html/rfc7231)
* [ https://www.w3.org/Protocols/rfc2616/rfc2616-sec13.html ](https://www.w3.org/Protocols/rfc2616/rfc2616-sec13.html)


#### CWE Id: [ 524 ](https://cwe.mitre.org/data/definitions/524.html)


#### WASC Id: 13

#### Source ID: 3


