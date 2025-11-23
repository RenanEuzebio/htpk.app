package com.myexample.webtoapk;

import android.content.DialogInterface;
import android.net.http.SslError;
import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;
import androidx.appcompat.app.AppCompatDelegate;
import android.os.Bundle;
import android.webkit.SslErrorHandler;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebChromeClient;
import android.view.View;
import android.widget.ProgressBar;
import android.widget.Toast;
import android.os.Handler;
import android.webkit.WebSettings;
import android.view.animation.Animation;
import android.view.animation.AnimationUtils;
import android.content.Intent;
import android.net.Uri;
import android.widget.EditText;
import android.webkit.JsResult;
import android.webkit.JsPromptResult;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.graphics.Bitmap;
import android.util.Log;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebResourceError;
import android.content.Context;
import android.content.ActivityNotFoundException;
import android.os.Looper;
import android.webkit.GeolocationPermissions;
import android.Manifest;
import android.content.pm.PackageManager;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import android.widget.TextView;
import android.app.Activity;
import android.webkit.ValueCallback;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import android.webkit.DownloadListener;
import android.app.DownloadManager;
import android.webkit.URLUtil;
import android.os.Environment;
import static android.content.Context.DOWNLOAD_SERVICE;
import android.os.Build;
import androidx.core.view.WindowCompat;
import android.graphics.Color;

public class MainActivity extends AppCompatActivity {
    // This value is replaced by the Python script during build
    private static final int LOCATION_PERMISSION_REQUEST_CODE = 1;

    private WebView webview;
    private ProgressBar spinner;
    private Animation fadeInAnimation;
    private View mainLayout;
    private View errorLayout;
    private ViewGroup parentLayout;
    private boolean errorOccurred = false;
    private ValueCallback<Uri[]> mFilePathCallback;
    private ActivityResultLauncher<Intent> fileChooserLauncher;

    // Defaults (overwritten by apply_config in make.sh)
    String mainURL = "https://github.com/Jipok";
    boolean requireDoubleBackToExit = true;
    boolean allowSubdomains = true;
    boolean enableExternalLinks = true;
    boolean openExternalLinksInBrowser = true;
    boolean confirmOpenInBrowser = true;
    boolean allowOpenMobileApp = false;
    boolean confirmOpenExternalApp = true;
    String cookies = "";
    String basicAuth = "";
    String userAgent = "";
    boolean blockLocalhostRequests = true;
    boolean JSEnabled = true;
    boolean JSCanOpenWindowsAutomatically = true;
    boolean DomStorageEnabled = true;
    boolean DatabaseEnabled = true;
    boolean MediaPlaybackRequiresUserGesture = true;
    boolean SavePassword = true;
    boolean AllowFileAccess = true;
    boolean AllowFileAccessFromFileURLs = true;
    boolean showDetailsOnErrorScreen = false;
    boolean forceLandscapeMode = false;
    boolean edgeToEdge = false;
    boolean forceDarkTheme = false;
    boolean DebugWebView = false;
    boolean geolocationEnabled = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        if (forceDarkTheme) {
            AppCompatDelegate.setDefaultNightMode(AppCompatDelegate.MODE_NIGHT_YES);
        }
        if (edgeToEdge) {
            WindowCompat.setDecorFitsSystemWindows(getWindow(), false);
        }

        super.onCreate(savedInstanceState);

        if (edgeToEdge) {
            getWindow().setStatusBarColor(Color.TRANSPARENT);
            getWindow().setNavigationBarColor(Color.TRANSPARENT);
        }

        if (forceLandscapeMode) {
            setRequestedOrientation(android.content.pm.ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE);
        }

        setContentView(R.layout.activity_main);
        mainLayout = findViewById(android.R.id.content);
        parentLayout = (ViewGroup) mainLayout.getParent();

        // Handle intent
        Intent intent = getIntent();
        String action = intent.getAction();
        Uri data = intent.getData();
        if (Intent.ACTION_VIEW.equals(action) && data != null) {
            mainURL = data.toString();
        }

        fadeInAnimation = AnimationUtils.loadAnimation(this, R.anim.fade_in);

        webview = findViewById(R.id.webView);
        spinner = findViewById(R.id.progressBar1);
        webview.setWebViewClient(new CustomWebViewClient());
        webview.setWebChromeClient(new CustomWebChrome());

        WebSettings webSettings = webview.getSettings();
        webSettings.setJavaScriptEnabled(JSEnabled);
        webSettings.setJavaScriptCanOpenWindowsAutomatically(JSCanOpenWindowsAutomatically);
        webSettings.setGeolocationEnabled(geolocationEnabled);
        webSettings.setDomStorageEnabled(DomStorageEnabled);
        webSettings.setDatabaseEnabled(DatabaseEnabled);
        webSettings.setMediaPlaybackRequiresUserGesture(MediaPlaybackRequiresUserGesture);
        webSettings.setSavePassword(SavePassword);
        webSettings.setAllowFileAccess(AllowFileAccess);
        webSettings.setAllowFileAccessFromFileURLs(AllowFileAccessFromFileURLs);
        webview.setWebContentsDebuggingEnabled(DebugWebView);

        if (!userAgent.isEmpty()) {
            webSettings.setUserAgentString(userAgent);
        }

        webSettings.setCacheMode(WebSettings.LOAD_DEFAULT);
        webview.setOverScrollMode(WebView.OVER_SCROLL_NEVER);

        CookieManager cookieManager = CookieManager.getInstance();
        CookieManager.getInstance().setAcceptThirdPartyCookies(webview, true);
        cookieManager.setCookie(mainURL, cookies);
        cookieManager.flush();

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this, new String[]{Manifest.permission.ACCESS_FINE_LOCATION}, LOCATION_PERMISSION_REQUEST_CODE);
        }

        fileChooserLauncher = registerForActivityResult(
            new ActivityResultContracts.StartActivityForResult(),
            result -> {
                Uri[] results = null;
                if (result.getResultCode() == Activity.RESULT_OK && result.getData() != null) {
                    Intent intentData = result.getData();
                    if (intentData.getClipData() != null) {
                        int count = intentData.getClipData().getItemCount();
                        results = new Uri[count];
                        for (int i = 0; i < count; i++) {
                            results[i] = intentData.getClipData().getItemAt(i).getUri();
                        }
                    } else if (intentData.getData() != null) {
                        results = new Uri[]{intentData.getData()};
                    }
                }
                if (mFilePathCallback != null) {
                    mFilePathCallback.onReceiveValue(results);
                    mFilePathCallback = null;
                }
            }
        );

        webview.setDownloadListener(new DownloadListener() {
            @Override
            public void onDownloadStart(String url, String userAgent, String contentDisposition, String mimetype, long contentLength) {
                DownloadManager downloadManager = (DownloadManager) getSystemService(DOWNLOAD_SERVICE);
                DownloadManager.Request request = new DownloadManager.Request(Uri.parse(url));
                request.setMimeType(mimetype);
                String cookies = CookieManager.getInstance().getCookie(url);
                request.addRequestHeader("cookie", cookies);
                request.addRequestHeader("User-Agent", userAgent);
                request.setDescription(getString(R.string.download_description));
                request.setTitle(URLUtil.guessFileName(url, contentDisposition, mimetype));
                request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                request.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, URLUtil.guessFileName(url, contentDisposition, mimetype));
                try {
                    downloadManager.enqueue(request);
                    Toast.makeText(getApplicationContext(), R.string.download_started, Toast.LENGTH_LONG).show();
                } catch (Exception e) {
                    Toast.makeText(getApplicationContext(), R.string.download_failed, Toast.LENGTH_LONG).show();
                    Log.e("WebToApk", "Failed to start download", e);
                }
            }
        });

        if (savedInstanceState != null) {
            webview.restoreState(savedInstanceState);
        } else {
            webview.loadUrl(mainURL);
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        webview.saveState(outState);
    }

    private class CustomWebChrome extends WebChromeClient {
        @Override
        public boolean onJsAlert(WebView view, String url, String message, final JsResult result) {
            new AlertDialog.Builder(MainActivity.this)
                .setMessage(message)
                .setPositiveButton(android.R.string.ok, (dialog, which) -> result.confirm())
                .setCancelable(false)
                .create()
                .show();
            return true;
        }

        @Override
        public boolean onJsConfirm(WebView view, String url, String message, final JsResult result) {
            new AlertDialog.Builder(MainActivity.this)
                .setMessage(message)
                .setPositiveButton(android.R.string.ok, (dialog, which) -> result.confirm())
                .setNegativeButton(android.R.string.cancel, (dialog, which) -> result.cancel())
                .setCancelable(false)
                .create()
                .show();
            return true;
        }

        @Override
        public boolean onJsPrompt(WebView view, String url, String message, String defaultValue, final JsPromptResult result) {
            final EditText input = new EditText(MainActivity.this);
            input.setText(defaultValue);
            new AlertDialog.Builder(MainActivity.this)
                .setMessage(message)
                .setView(input)
                .setPositiveButton(android.R.string.ok, (dialog, which) -> result.confirm(input.getText().toString()))
                .setNegativeButton(android.R.string.cancel, (dialog, which) -> result.cancel())
                .setCancelable(false)
                .create()
                .show();
            return true;
        }

        @Override
        public void onGeolocationPermissionsShowPrompt(String origin, GeolocationPermissions.Callback callback) {
            callback.invoke(origin, true, false);
        }

        private View mCustomView;
        private WebChromeClient.CustomViewCallback mCustomViewCallback;
        private int mOriginalOrientation;
        private int mOriginalSystemUiVisibility;

        @Override
        public void onHideCustomView() {
            ((FrameLayout)getWindow().getDecorView()).removeView(mCustomView);
            mCustomView = null;
            getWindow().getDecorView().setSystemUiVisibility(mOriginalSystemUiVisibility);
            setRequestedOrientation(mOriginalOrientation);
            mCustomViewCallback.onCustomViewHidden();
            mCustomViewCallback = null;
        }

        @Override
        public void onShowCustomView(View view, WebChromeClient.CustomViewCallback callback) {
            if (mCustomView != null) {
                onHideCustomView();
                return;
            }
            mCustomView = view;
            mOriginalSystemUiVisibility = getWindow().getDecorView().getSystemUiVisibility();
            mOriginalOrientation = getRequestedOrientation();
            mCustomViewCallback = callback;
            ((FrameLayout)getWindow().getDecorView()).addView(mCustomView,
                new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));
            getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LAYOUT_STABLE |
                    View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION |
                    View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN |
                    View.SYSTEM_UI_FLAG_HIDE_NAVIGATION |
                    View.SYSTEM_UI_FLAG_FULLSCREEN |
                    View.SYSTEM_UI_FLAG_IMMERSIVE);
        }

        @Override
        public boolean onShowFileChooser(WebView webView, ValueCallback<Uri[]> filePathCallback, FileChooserParams fileChooserParams) {
            if (mFilePathCallback != null) {
                mFilePathCallback.onReceiveValue(null);
            }
            mFilePathCallback = filePathCallback;

            Intent intent = new Intent(Intent.ACTION_GET_CONTENT);
            intent.addCategory(Intent.CATEGORY_OPENABLE);
            intent.setType("image/*");

            String[] acceptTypes = fileChooserParams.getAcceptTypes();
            if (acceptTypes.length > 0 && acceptTypes[0] != null && !acceptTypes[0].isEmpty()) {
                if (acceptTypes[0].contains("image")) {
                    intent.setType("image/*");
                } else {
                    intent.setType("*/*");
                }
            }

            if (fileChooserParams.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE) {
                intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
            }

            Intent chooserIntent = Intent.createChooser(intent, "Select File");
            try {
                fileChooserLauncher.launch(chooserIntent);
            } catch (ActivityNotFoundException e) {
                mFilePathCallback = null;
                Toast.makeText(MainActivity.this, "Cannot open file chooser", Toast.LENGTH_LONG).show();
                return false;
            }
            return true;
        }
    }

    private class CustomWebViewClient extends WebViewClient {
        @Override
        public void onReceivedSslError(WebView view, final SslErrorHandler handler, SslError error) {
            final AlertDialog.Builder builder = new AlertDialog.Builder(MainActivity.this);
            builder.setMessage(R.string.notification_error_ssl_cert_invalid);
            builder.setPositiveButton("continue", (dialog, which) -> handler.proceed());
            builder.setNegativeButton("cancel", (dialog, which) -> handler.cancel());
            builder.create().show();
        }

        @Override
        public void onReceivedHttpAuthRequest(final WebView view, final android.webkit.HttpAuthHandler handler, String host, String realm) {
            if (MainActivity.this.basicAuth != null && !MainActivity.this.basicAuth.isEmpty()) {
                String[] parts = MainActivity.this.basicAuth.split(":", 2);
                if (parts.length == 2) {
                    handler.proceed(parts[0], parts[1]);
                    return;
                }
            }
            final View dialogView = getLayoutInflater().inflate(R.layout.auth_dialog, null);
            final EditText usernameInput = dialogView.findViewById(R.id.username);
            final EditText passwordInput = dialogView.findViewById(R.id.password);

            new AlertDialog.Builder(MainActivity.this)
                .setTitle("Authentication Required")
                .setView(dialogView)
                .setPositiveButton("OK", (dialog, which) -> {
                    String user = usernameInput.getText().toString();
                    String pass = passwordInput.getText().toString();
                    handler.proceed(user, pass);
                })
                .setNegativeButton("Cancel", (dialog, which) -> handler.cancel())
                .show();
        }

        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            String url = request.getUrl().toString();
            if (!url.startsWith("http://") && !url.startsWith("https://")) {
                if (allowOpenMobileApp) {
                     try {
                        Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
                        view.getContext().startActivity(intent);
                    } catch (ActivityNotFoundException e) {
                        Log.e("WebToApk", "No app found for URL: " + url);
                    }
                }
                return true; 
            }

            String urlDomain = request.getUrl().getHost();
            String mainDomain = Uri.parse(mainURL).getHost();

            if (urlDomain == null || mainDomain == null) return handleExternalLink(url, view);

            boolean isInternalLink;
            if (allowSubdomains) {
                isInternalLink = urlDomain.endsWith(mainDomain) || mainDomain.endsWith(urlDomain);
            } else {
                isInternalLink = urlDomain.equals(mainDomain);
            }

            if (isInternalLink) return false;
            return handleExternalLink(url, view);
        }

        private boolean handleExternalLink(String url, WebView view) {
            if (!enableExternalLinks) return true;
            if (openExternalLinksInBrowser) {
                if (confirmOpenInBrowser) {
                    new AlertDialog.Builder(view.getContext())
                        .setTitle(R.string.external_link)
                        .setMessage(R.string.open_in_browser)
                        .setPositiveButton(android.R.string.yes, (dialog, which) -> {
                            Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
                            view.getContext().startActivity(intent);
                        })
                        .setNegativeButton(android.R.string.no, null)
                        .show();
                    return true;
                } else {
                    Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
                    view.getContext().startActivity(intent);
                    return true;
                }
            }
            return false;
        }

        @Override
        public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
            String host = request.getUrl().getHost();
            if (blockLocalhostRequests && ("127.0.0.1".equals(host) || "localhost".equalsIgnoreCase(host) || "::1".equals(host))) {
                return new WebResourceResponse("text/plain", "UTF-8", null);
            }
            return super.shouldInterceptRequest(view, request);
        }

        @Override
        public void onPageFinished(WebView webview, String url) {
            if (!errorOccurred) {
                spinner.setVisibility(View.GONE);
                if (!webview.isShown()) {
                    webview.startAnimation(fadeInAnimation);
                    webview.setVisibility(View.VISIBLE);
                }
            }
            super.onPageFinished(webview, url);
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
            if (request.isForMainFrame()) {
                errorOccurred = true;
                errorLayout = getLayoutInflater().inflate(R.layout.error, parentLayout, false);
                parentLayout.removeView(mainLayout);
                parentLayout.addView(errorLayout);
                if (showDetailsOnErrorScreen) {
                    TextView errorTextView = errorLayout.findViewById(R.id.errorText);
                    if (errorTextView != null) {
                        errorTextView.setText("Error: " + error.getDescription());
                    }
                }
            }
        }
    }

    boolean doubleBackToExitPressedOnce = false;

    @Override
    public void onBackPressed() {
        if (webview.canGoBack()) {
            webview.goBack();
        } else {
            if (doubleBackToExitPressedOnce || !requireDoubleBackToExit) {
                finish();
                return;
            }
            this.doubleBackToExitPressedOnce = true;
            Toast.makeText(this, R.string.exit_app, Toast.LENGTH_SHORT).show();
            new Handler().postDelayed(() -> doubleBackToExitPressedOnce = false, 2000);
        }
    }

    public void tryAgain(View v) {
        parentLayout.removeView(errorLayout);
        parentLayout.addView(mainLayout);
        webview.setVisibility(View.GONE);
        spinner.setVisibility(View.VISIBLE);
        errorOccurred = false;
        webview.reload();
    }
}
