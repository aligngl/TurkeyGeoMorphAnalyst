<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.16" styleCategories="Symbology">
  <pipe>
    <rasterrenderer type="singlebandpseudocolor" band="1" opacity="1" alphaBand="-1" classificationMin="-10" classificationMax="10">
      <rastershader>
        <colorrampshader colorRampType="DISCRETE" classificationMode="1" clip="0">
          <item alpha="255" value="-10" label="Güçlü konkav" color="#053061"/>
          <item alpha="255" value="-3" label="Belirgin konkav" color="#2166ac"/>
          <item alpha="255" value="-1" label="Zayıf konkav" color="#92c5de"/>
          <item alpha="255" value="0" label="Nötr / düz" color="#f7f7f7"/>
          <item alpha="255" value="1" label="Zayıf konveks" color="#f4a582"/>
          <item alpha="255" value="3" label="Belirgin konveks" color="#d6604d"/>
          <item alpha="255" value="10" label="Güçlü konveks" color="#67001f"/>
        </colorrampshader>
      </rastershader>
    </rasterrenderer>
  </pipe>
</qgis>
