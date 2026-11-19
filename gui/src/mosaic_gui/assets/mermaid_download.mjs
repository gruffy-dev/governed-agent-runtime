document.addEventListener('click', event => {
    const button = event.target.closest('.mermaid-download');
    const diagram = button?.closest('.mermaid-card')?.querySelector('.mermaid-visual svg');
    if (!diagram) return;

    const exportedDiagram = diagram.cloneNode(true);
    const {width, height} = diagram.viewBox.baseVal;
    if (width > 0 && height > 0) {
        exportedDiagram.setAttribute('width', String(width));
        exportedDiagram.setAttribute('height', String(height));
    }
    exportedDiagram.style.removeProperty('max-width');

    const svg = new XMLSerializer().serializeToString(exportedDiagram);
    const url = URL.createObjectURL(new Blob([svg], {type: 'image/svg+xml'}));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'mosaic-diagram.svg';
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
});
